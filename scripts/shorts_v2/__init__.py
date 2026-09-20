"""Independent Q Station Shorts V2.2 contracts and orchestration.

This package deliberately does not import the legacy motion modules.  Legacy
runs are selected before this package is used and retain their frozen path.
"""

from .contracts import ContractError, normalize_engine_settings
from .creative import build_character_performance_context, load_character_profiles

__all__ = ["ContractError", "build_character_performance_context", "load_character_profiles", "normalize_engine_settings"]
