"""Independent Q Station Shorts V2.2 contracts and orchestration.

This package deliberately does not import the legacy motion modules.  Legacy
runs are selected before this package is used and retain their frozen path.
"""

from .contracts import ContractError, normalize_engine_settings
from .creative import build_character_performance_context, load_character_profiles
from .performance import compile_voice
from .editing import FrameClock, compile_timeline, render_timeline, solve_geometry
from .presentation import build_caption_plan, build_sound_plan, compile_presentation
from .revision import RevisionStore, plan_revision

__all__ = ["ContractError", "FrameClock", "RevisionStore", "build_caption_plan", "build_character_performance_context", "build_sound_plan", "compile_presentation", "compile_timeline", "compile_voice", "load_character_profiles", "normalize_engine_settings", "plan_revision", "render_timeline", "solve_geometry"]
