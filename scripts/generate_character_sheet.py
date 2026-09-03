#!/usr/bin/env python3
"""Generate canonical character sheet for Question Harvest (§13, §47).

Primary: Gemini Web via Ordak browser automation (Nano Banana Pro).
Fallback: deterministic synthetic PIL sheet when browser unavailable (for pipeline unblocking).

Outputs:
  projects/question_harvest/visual_presets/001_home_world/character_sheet.png

The fallback is clearly marked and should be replaced via real Gemini when credentials ready.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "projects" / "question_harvest" / "visual_presets" / "001_home_world" / "character_sheet.png"

CHARACTER_PROMPT = """Create a canonical character reference sheet for a YouTube educational cartoon.

CHARACTER — tall/slim simplified adult male cartoon, prominent brown/chestnut hair silhouette, beard/moustache/goatee, light moss/green sweater, dark blue overalls, rust/orange boots, simple bold linework, approachable hand-drawn educational cartoon language.

STYLE — clean dark outlines, warm rustic educational animation, simplified geometry, muted natural palette, readable silhouettes, no photorealism, no 3D CGI, no anime, no high-detail semi-realistic.

OUTPUT — exactly one image: 9:16 full-body turnaround (front, 3/4, side) on clean off-white background, centered, consistent proportions, same outfit in all views. No text, no watermark, no grid beyond light guide lines.
"""


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_synthetic(output: Path) -> dict:
    """Fallback deterministic synthetic sheet when Gemini unavailable."""
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (252, 248, 240))
    draw = ImageDraw.Draw(img)
    # title
    draw.text((W//2, 70), "CHARACTER SHEET — FALLBACK", fill=(90, 70, 60), anchor="mm", font=ImageFont.load_default())
    draw.text((W//2, 100), "Tall slim male — green sweater / blue overalls / orange boots", fill=(120, 100, 90), anchor="mm", font=ImageFont.load_default())
    # draw three simple stick-figure style characters
    # positions: left, center, right
    centers = [W//2 - 300, W//2, W//2 + 300]
    labels = ["FRONT", "3/4", "SIDE"]
    for cx, label in zip(centers, labels):
        # head
        draw.ellipse([cx-60, 350-60, cx+60, 350+60], fill=(240, 210, 180), outline=(60, 40, 30), width=4)
        # hair (chestnut)
        draw.arc([cx-65, 300-20, cx+65, 360], start=200, end=340, fill=(110, 60, 30), width=14)
        # beard
        draw.arc([cx-45, 370, cx+45, 410], start=0, end=180, fill=(90, 55, 35), width=6)
        # sweater (moss green)
        draw.rounded_rectangle([cx-70, 420, cx+70, 620], radius=18, fill=(140, 160, 90), outline=(70, 85, 50), width=3)
        # overalls (dark blue)
        draw.rectangle([cx-65, 620, cx+65, 950], fill=(40, 60, 110), outline=(25, 35, 80), width=3)
        # overalls straps
        draw.rectangle([cx-50, 420, cx-30, 540], fill=(40, 60, 110))
        draw.rectangle([cx+30, 420, cx+50, 540], fill=(40, 60, 110))
        # boots (rust orange)
        draw.ellipse([cx-55, 950, cx-15, 1020], fill=(180, 90, 40), outline=(120, 60, 30), width=2)
        draw.ellipse([cx+15, 950, cx+55, 1020], fill=(180, 90, 40), outline=(120, 60, 30), width=2)
        draw.text((cx, 1060), label, fill=(80, 60, 50), anchor="mm", font=ImageFont.load_default())
    # footnotes
    draw.text((W//2, H-80), "FALLBACK SYNTHETIC — replace via Gemini Nano Banana Pro when browser ready", fill=(160, 140, 120), anchor="mm", font=ImageFont.load_default())
    draw.text((W//2, H-50), "Prompt: tall/slim, chestnut hair, beard, moss sweater, blue overalls, orange boots", fill=(160, 140, 120), anchor="mm", font=ImageFont.load_default())
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "PNG", optimize=True)
    return {"output": str(output), "sha256": sha256(output), "provider": "synthetic_fallback", "note": "Fallback — replace with Gemini Pro result"}


def try_gemini(output: Path, timeout: int = 600) -> dict:
    """Attempt real Gemini generation via Ordak."""
    try:
        import httpx
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        base = os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        # health check
        with httpx.Client(timeout=15, trust_env=False) as c:
            h = c.get(f"{base}/api/health")
            h.raise_for_status()
            d = c.get(f"{base}/api/diagnostics")
            d.raise_for_status()
            diag = d.json()
            if not diag.get("chrome_running"):
                raise RuntimeError("Chrome not running")
            gemini_state = (diag.get("provider_sessions") or {}).get("gemini") or {}
            if gemini_state.get("login_state") not in ("ready", None) and not gemini_state.get("logged_in"):
                raise RuntimeError(f"Gemini login_state={gemini_state.get('login_state')} not ready")
        # submit Gemini image job via generic jobs API
        with httpx.Client(timeout=30, trust_env=False) as c:
            # No reference images for character sheet creation — prompt only
            data = {
                "question": CHARACTER_PROMPT,
                "provider": "gemini",
                "mode": "image_generate",
                "start_new_chat": "true",
                "wait_for_completion": "true",
                "wait_timeout_seconds": str(timeout),
            }
            resp = c.post(f"{base}/api/jobs", data=data, files=[])
            resp.raise_for_status()
            created = resp.json()
            job_id = created["job_id"]
            print(f"Gemini job {job_id} created, polling {timeout}s...")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                jr = c.get(f"{base}/api/jobs/{job_id}")
                jr.raise_for_status()
                job = jr.json()
                status = job.get("status")
                if status in ("completed", "failed", "manual_verification_required", "cancelled"):
                    if status != "completed":
                        raise RuntimeError(f"Gemini job {job_id} status {status}: {job.get('error_message')}")
                    outputs = job.get("output_images") or []
                    if not outputs:
                        raise RuntimeError("Gemini job completed but produced no output_images")
                    # download first image
                    artifact = outputs[0]
                    url = artifact if artifact.startswith("http") else f"{base}/{artifact.lstrip('/')}"
                    dl = c.get(url)
                    dl.raise_for_status()
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(dl.content)
                    # validate
                    with Image.open(output) as im:
                        im.verify()
                    with Image.open(output) as im:
                        w, h = im.size
                    return {
                        "output": str(output),
                        "sha256": sha256(output),
                        "provider": "gemini",
                        "model": "nano_banana_pro",
                        "size": f"{w}x{h}",
                        "job_id": job_id,
                        "artifact": artifact,
                    }
                time.sleep(5)
            raise RuntimeError("Gemini generation timeout")
    except Exception as e:
        raise RuntimeError(f"Gemini generation failed: {e}") from e


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Question Harvest character_sheet via Gemini or synthetic fallback")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="Overwrite even if exists")
    parser.add_argument("--fallback-only", action="store_true", help="Force synthetic fallback without trying Gemini")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        print(f"Exists (use --force to regenerate): {args.output}")
        print(f"SHA256: {sha256(args.output)}")
        return

    if args.fallback_only:
        meta = generate_synthetic(args.output)
        print(json.dumps(meta, indent=2))
        return

    try:
        meta = try_gemini(args.output)
        print(json.dumps(meta, indent=2))
        print(f"✅ Gemini character sheet at {args.output}")
    except Exception as e:
        print(f"Gemini failed: {e}")
        print("→ Generating synthetic fallback to unblock pipeline...")
        meta = generate_synthetic(args.output)
        meta["gemini_error"] = str(e)
        print(json.dumps(meta, indent=2))
        print(f"⚠️ Fallback at {args.output} — replace later via --force + Gemini")


if __name__ == "__main__":
    main()
