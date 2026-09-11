"""Bounded, atomic derivative creation for concurrent Studio requests."""
from __future__ import annotations

import hashlib
import subprocess
import threading
import uuid
from pathlib import Path

_LOCKS = [threading.Lock() for _ in range(64)]
_WORKERS = threading.BoundedSemaphore(2)


def preview(source: Path, cache: Path, *, style: bool | str = False) -> tuple[Path, str]:
    suffix = source.suffix.lower()
    if suffix in {".json", ".txt", ".md", ".ass"}:
        return source, "text/plain; charset=utf-8"
    formats = {".png": (".jpg", "image/jpeg"), ".jpg": (".jpg", "image/jpeg"),
               ".jpeg": (".jpg", "image/jpeg"), ".webp": (".jpg", "image/jpeg")}
    formats.update({s: (".mp4", "video/mp4") for s in (".mp4", ".mov", ".webm")})
    formats.update({s: (".ogg", "audio/ogg") for s in (".mp3", ".wav", ".m4a", ".ogg", ".flac")})
    if suffix not in formats:
        raise ValueError("This artifact has no safe panel preview.")
    stat = source.stat()
    identity = (stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
    key = hashlib.sha256(f"v2:{source.resolve()}:{identity}:{style}".encode()).hexdigest()[:24]
    extension, mime = formats[suffix]
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / (key + extension)
    with _LOCKS[int(key[:8], 16) % len(_LOCKS)]:
        if output.is_file() and output.stat().st_size:
            return output, mime
        temporary = cache / f".{key}.{uuid.uuid4().hex}{extension}"
        try:
            with _WORKERS:
                if mime.startswith("image"):
                    from PIL import Image, ImageOps
                    with Image.open(source) as image:
                        image = ImageOps.exif_transpose(image)
                        large_style = style == "large"
                        image.thumbnail((1200, 900) if large_style else ((420, 300) if style else (480, 480)), Image.Resampling.LANCZOS)
                        image.convert("RGB").save(temporary, "JPEG", quality=76 if large_style else (52 if style else 48), optimize=True)
                else:
                    options = (["-vf", "scale=min(360\\,iw):-2", "-c:v", "libx264", "-crf", "35", "-preset", "veryfast", "-an", "-movflags", "+faststart"]
                               if mime.startswith("video") else ["-c:a", "libopus", "-b:a", "32k", "-ac", "1"])
                    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", str(source), *options, str(temporary)],
                                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
            current = source.stat()
            if identity != (current.st_mtime_ns, current.st_size, current.st_ctime_ns):
                raise ValueError("Source changed while building preview; retry the request.")
            if not temporary.is_file() or not temporary.stat().st_size:
                raise ValueError("Preview generation returned an empty file.")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return output, mime
