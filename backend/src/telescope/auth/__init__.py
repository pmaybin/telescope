"""Authentication: every mode yields a `Principal` (ADR-0013)."""

from telescope.auth.authenticator import Authenticator
from telescope.auth.principal import SYSTEM, Principal, current_principal

__all__ = ["SYSTEM", "Authenticator", "Principal", "current_principal"]
