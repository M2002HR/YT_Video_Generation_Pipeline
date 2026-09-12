"""Regression: a trim-only resume must reuse world_keyframe.

stage_world_keyframe appends a runtime-only operator suffix to the base prompt
file before writing the receipt. receipt_status used to compare the raw base
file against the recorded runtime prompt and report "Image prompt changed",
forcing a fresh Gemini generation (and a cascade over beats + Flow Clip B)
even when the fingerprint proved the inputs identical.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from PIL import Image

from image_artifacts import CONTRACT_VERSION, digest, receipt_status, request_fingerprint
from ordak_jobs import Reference

OPERATOR_SUFFIX = (
    "\n\nThe attached operator_style_reference is style-only. Preserve the "
    "newly established world plan while echoing only its texture, palette, "
    "line work and lighting; do not copy its subject, text, people, logo, "
    "or composition."
)


def picture(path: Path, seed: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import random

    Image.frombytes(
        "RGB", (64, 64), random.Random(seed).randbytes(64 * 64 * 3)
    ).save(path)
    return path


def test_trim_only_resume_reuses_world_keyframe(tmp_path):
    project = tmp_path
    base_prompt = "world keyframe base prompt. " * 20
    (project / "references").mkdir(parents=True)
    (project / "references" / "world_keyframe_prompt.txt").write_text(
        base_prompt + "\n", encoding="utf-8"
    )
    output = picture(project / "references" / "world_keyframe.png")
    anchor = picture(project / "references" / "world_style_anchor.png", 2)
    operator_old = picture(project / "launch" / "style_reference.png", 3)
    # Panel copies the brief (and its style reference) into a config revision
    # on resume. Same bytes, different path — like 029's 0.2 -> 0.32 change.
    operator_new = project / "launch" / "config_revisions" / "rev1" / "style_reference.png"
    operator_new.parent.mkdir(parents=True, exist_ok=True)
    operator_new.write_bytes(operator_old.read_bytes())

    runtime_prompt = base_prompt.rstrip() + OPERATOR_SUFFIX
    model = "nano_banana_2"
    refs_old = [
        Reference("style_reference", anchor),
        Reference("operator_style_reference", operator_old),
    ]
    fingerprint = request_fingerprint(runtime_prompt, model, refs_old)
    receipt = project / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "model_verified": True,
                "quality_check": {"passed": True},
                "requested_model": model,
                "output_sha256": digest(output),
                "prompt": runtime_prompt,
                "prompt_sha256": __import__("hashlib").sha256(
                    runtime_prompt.encode()
                ).hexdigest(),
                "request_fingerprint": fingerprint,
                "references": [
                    {
                        "role": "style_reference",
                        "path": str(anchor),
                        "sha256": digest(anchor),
                    },
                    {
                        "role": "operator_style_reference",
                        "path": str(operator_old),
                        "sha256": digest(operator_old),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    # The resume resolves the operator reference through the new brief path,
    # but the bytes are identical so the fingerprint (SHA-based) is unchanged.
    refs_new = [
        Reference("style_reference", anchor),
        Reference("operator_style_reference", operator_new),
    ]
    resumed = request_fingerprint(runtime_prompt, model, refs_new)
    assert resumed == fingerprint
    assert (
        receipt_status(project, output, receipt, fingerprint=resumed)["status"]
        == "verified"
    )
    # A genuine prompt change must still be stale.
    assert (
        receipt_status(
            project,
            output,
            receipt,
            fingerprint=request_fingerprint("a different scene", model, refs_new),
        )["status"]
        == "stale"
    )
