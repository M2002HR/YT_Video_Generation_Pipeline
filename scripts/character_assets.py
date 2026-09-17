"""Read-only readiness checks for operator-provisioned character references.

Bundled packs keep their historical strict loading rules. Operator packs may be deployed
before their artwork, but are never selectable until the real image is usable. Nothing in
this module creates artwork, calls a provider, or changes episode state.
"""
from __future__ import annotations

import warnings
from pathlib import Path

MIN_REFERENCE_BYTES = 10_000  # Same lower bound as the production image gate.
MIN_REFERENCE_EDGE = 256
_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


def operator_reference_error(path: Path) -> str | None:
    """Return an actionable failure without taking other character packs offline."""
    from PIL import Image

    path = Path(path)
    try:
        if not path.is_file():
            return f"Install the operator-provided character sheet at {path}."
        if path.stat().st_size < MIN_REFERENCE_BYTES:
            return f"Character sheet is empty or too small (minimum {MIN_REFERENCE_BYTES} bytes): {path}"
        expected = _FORMATS.get(path.suffix.lower())
        if expected is None:
            return f"Unsupported character sheet extension: {path}"
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != expected:
                    return f"Export a real {expected} image, not a renamed file: {path}"
                if min(image.size) < MIN_REFERENCE_EDGE:
                    return f"Character sheet must be at least {MIN_REFERENCE_EDGE} pixels on each edge: {path}"
                if getattr(image, "n_frames", 1) != 1:
                    return f"Character sheet must be a single still image: {path}"
                image.verify()
            # verify() checks the container; load() also checks that pixels decode.
            with Image.open(path) as image:
                image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        return f"Character sheet is unreadable or corrupt: {path} ({type(exc).__name__})"
    return None


def registry_asset_revision(registry_path: Path) -> tuple[tuple[str, int, int, int], ...]:
    """Track additions, removals and replacements, not only the newest mtime.

    Upload tools can preserve old mtimes; deleting a sheet need not change another file's
    mtime. ctime/size and the sorted path set prevent either case from reusing a stale
    available/unavailable catalog. No pixel hashing or decoding is done on cache hits.
    """
    root = registry_path.parent
    rows = []
    for path in root.rglob("*"):
        if path.suffix.lower() not in {".json", ".md", ".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            if path.is_file():
                stat = path.stat()
                rows.append((str(path.relative_to(root)), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
        except FileNotFoundError:
            # An atomic operator upload/deletion raced this scan; the next read sees it.
            continue
    return tuple(sorted(rows))
