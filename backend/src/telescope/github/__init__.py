"""GitHub REST client and response mapping."""

from telescope.github.client import GitHubClient
from telescope.github.mapping import parse_repo

__all__ = ["GitHubClient", "parse_repo"]
