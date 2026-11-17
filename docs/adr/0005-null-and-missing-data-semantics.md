# ADR-0005: Null and missing-data semantics

- Status: Accepted
- Date: 2026-11-17

## Context
GitHub returns `description: ""`, `language: null`, `license: null`, `license.spdx_id: "NOASSERTION"` and sometimes a null `pushed_at` ([schema, research section 6](https://docs.github.com/en/rest/repos/repos#list-organization-repositories)). Sorting and filtering over nullable fields needs rules that are total, deterministic and testable, otherwise keyset pagination (ADR-0004) breaks. The same "no value" must not have two spellings.

## Options considered
- **Pass GitHub's values through unchanged**: simple, but clients must handle `""` and `null` identically, and `NOASSERTION` leaks a magic string into an SPDX field.
- **Normalise at ingestion**: one representation (`null`) in the contract, so every layer downstream is simpler. Chosen.
- **Nulls first / nulls follow direction**: SQL-style defaults flip the null position with the direction, so "newest first" would put unknown dates on top.
- **Nulls always last**: unknown values never crowd the head of the list. Chosen.

## Decision
- **Empty -> null** (ingestion, `github/mapping.py`): strings are stripped, and `""` becomes `null` for `description` and `language`. `license` is `null` when absent. `license.spdx_id` is `null` when GitHub says `NOASSERTION` (the `name` is kept). `topics` defaults to `[]`. Datetimes are nullable.
- **Sorting**: key per sort field (`stars`, `updated_at`, `pushed_at`, `name.casefold()`), then the effective order (`desc` for stars/updated/pushed, `asc` for name). **Nulls sort last regardless of direction.** Today only `pushed_at` is realistically null, but the rule is general, so a new nullable sort key needs no new decision.
- **Tiebreaker**: `id` ascending, always, irrespective of the order direction. This makes the ordering total and stable, which is what lets `(sort value, id)` act as a unique keyset position.
- **Language filter**: case-insensitive equality on the primary language. The reserved value `none` (case-insensitive) matches `language is null`. GitHub has no real language named "none", and Search has no `language:none` equivalent (ADR-0002), which is one more reason to filter locally.
- **Name**: compared with `casefold()` (not `lower()`), so Unicode case folding is consistent. Org names are lower-cased for the cache key.
- `language` input is stripped, and a blank value is treated as unset.

## Consequences
- Pro: one representation of "unknown" across API, cache and UI, with the UI rendering a single placeholder.
- Pro: the ordering is a pure function of the data, so property-style walk tests (ADR-0011) can assert "every item exactly once".
- Con: a real language literally named `None` (none exists today) would be unreachable by name.
- Con: collapsing `""` and `null` loses a distinction GitHub may draw. We judged it meaningless for a repo description.
- Con: "descending but nulls last" is a custom comparison (a tuple key `(is_null, directed value, id)`), slightly more code than a plain `sorted(reverse=True)`. It is covered by tests in both directions.
