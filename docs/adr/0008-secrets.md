# ADR-0008: Secrets

- Status: Accepted
- Date: 2026-11-17

## Context
The only secret is an optional GitHub token (ADR-0007). It must never reach git, logs, responses or the frontend bundle. The setup must work with no token and with one, locally via Compose, and have a credible production story.

## Options considered
- **Committed config / baked into images**: leaks via git history and image layers. Rejected.
- **`.env` file (git-ignored) with a committed `.env.example`**: the simplest local workflow, and Compose and pydantic-settings both read it. Chosen for development.
- **Secrets manager injecting environment variables** (Doppler, 1Password Connect/CLI, AWS Secrets Manager via the ECS/EKS integrations): rotation, audit and access control. Chosen for production. No application code change is needed, because the app reads `GITHUB_TOKEN` from the environment either way.
- **Docker/Compose `secrets:` files**: a good fit for Swarm, but the app would need a file-reading path for little gain here.
- **Passing the token from the browser**: would put a credential in the frontend. Rejected.

## Decision
- Config via `pydantic-settings` (`Settings`): `GITHUB_TOKEN` is a `SecretStr | None`, and an empty or blank value is normalised to `None` (so `GITHUB_TOKEN=` in Compose means tokenless).
- `.env` is in `.gitignore` (`.env.*` too, except `.env.example`). `.env.example` documents each variable with an empty token. Compose passes `GITHUB_TOKEN: ${GITHUB_TOKEN:-}` and works with no `.env`.
- The token is used in exactly one place, the `Authorization: Bearer` header of the GitHub client, and only when set.
- **Log redaction**: a logging filter replaces the token value and any `Authorization: ...` or `Bearer ...` text with `[REDACTED]` in the message, args and extras. Request logging never includes request headers. `SecretStr` keeps the value out of `repr` and tracebacks. The filter is idempotent (ADR-0009).
- The token never appears in responses, problem details, metrics labels, span attributes or the frontend. The browser only talks to our API (the nginx `/api/` proxy).
- **Token scope**: a [fine-grained PAT](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) with **public repositories, read-only** access and no extra permissions. We only read public data (`type=public`, ADR-0002), so even a leaked token can read nothing the world cannot.
- **Production**: a secrets manager (Doppler, 1Password Connect, or AWS Secrets Manager) injects `GITHUB_TOKEN` into the container environment at start. Nothing is written to the image.

## Consequences
- Pro: zero-config tokenless start, and a one-line change to add a token locally.
- Pro: the blast radius of a leak is limited by the scope, and redaction is tested (ADR-0011).
- Con: environment variables are visible to anyone who can inspect the process or container. A file-mounted secret is slightly safer, and could be added with the `*_FILE` convention if needed.
- Con: redaction is pattern-based. A token embedded in an unexpected form (e.g. base64) would not match, so the code avoids logging credentials in the first place and the filter is the safety net.
- Con: no rotation story beyond "replace the env var and restart". That is acceptable for this scope.
