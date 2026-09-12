"""Image receipts are commit records, not just download logs."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = 1


def _model_bound(receipt: dict) -> bool:
    """Catalog and canonical assets are intentionally shared across model upgrades."""
    return receipt.get("source_type") not in {"catalog", "canonical"}


@lru_cache(maxsize=1024)
def _digest(path: str, modified: int, size: int, changed: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(path: Path) -> str:
    stat = path.stat()
    return _digest(str(path.resolve()), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)


def request_fingerprint(prompt: str, model: str, references) -> str:
    payload = {"version": CONTRACT_VERSION, "prompt": prompt, "model": model,
               "quality": "best", "aspect_ratio": "9:16",
               "references": [{"role": ref.role, "sha256": digest(Path(ref.path))} for ref in references]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def receipt_status(project: Path, output: Path, receipt_path: Path, *, fingerprint: str | None = None) -> dict:
    """Read-only validation, also used by Studio. Legacy images stay visible as unverified."""
    receipt: dict | None = None

    def outcome(status: str, reason: str) -> dict:
        data = {"status": status, "reason": reason}
        if receipt is not None:
            data["job_id"] = receipt.get("job_id")
            data["references"] = [
                {
                    "role": str(ref.get("role") or "unknown"),
                    "path": str(ref.get("path") or ""),
                    "sha256": str(ref.get("sha256") or ""),
                }
                for ref in (receipt.get("references") or [])
                if isinstance(ref, dict)
            ]
        return data

    try:
        if not output.is_file():
            return outcome("missing", "Image is missing")
        if not receipt_path.is_file():
            return outcome("unverified", "No image receipt")
        receipt = json.loads(receipt_path.read_text())
        if not isinstance(receipt, dict):
            raise ValueError("Invalid receipt")
        if digest(output) != receipt.get("output_sha256"):
            return outcome("stale", "Image differs from its receipt")
        # The request fingerprint already binds the full runtime prompt, model and
        # reference bytes. The prompt-file check below compares the *base* file
        # against the recorded *runtime* prompt, which for world_keyframe includes
        # a runtime-only operator suffix (see stage_world_keyframe). When the
        # caller supplies a fingerprint and it matches, the inputs are proven
        # identical, so the weaker file-content heuristic must not override it.
        fingerprint_matches = (
            fingerprint is not None
            and receipt.get("request_fingerprint") == fingerprint
        )
        launch = project / "launch/LAUNCH_REQUEST.json"
        if _model_bound(receipt) and launch.is_file():
            model = json.loads(launch.read_text()).get("image_generation", {}).get("model")
            if model and receipt.get("requested_model") != model:
                return outcome("stale", "Requested image model changed")
        prompt_path = None
        if output.stem == "world_keyframe":
            prompt_path = project / "references/world_keyframe_prompt.txt"
        elif output.stem.startswith("beat_"):
            base = project / "beats" / (output.stem.upper() + "_PROMPT.md")
            revision = base.with_suffix(".revision.md")
            prompt_path = revision if revision.is_file() else base
        if prompt_path and prompt_path.is_file() and not fingerprint_matches:
            current_prompt = prompt_path.read_text().strip()
            recorded_prompt = str(receipt.get("prompt") or "").strip()
            if recorded_prompt and current_prompt != recorded_prompt:
                return outcome("stale", "Image prompt changed")
        for ref in receipt.get("references") or []:
            path = Path(ref["path"])
            if not path.is_absolute():
                path = ROOT / path if path.parts[0] in {"videos", "projects"} else project / path
            # Receipts never authorize reading files outside the repository/project.
            resolved = path.resolve()
            if not (resolved.is_relative_to(ROOT) or resolved.is_relative_to(project.resolve())):
                raise ValueError("Reference outside project")
            if not path.is_file() or digest(path) != ref.get("sha256"):
                return outcome("stale", f"Reference changed: {ref.get('role', 'unknown')}")
        if fingerprint is not None and receipt.get("request_fingerprint") != fingerprint:
            return outcome("stale", "Image inputs or generation contract changed")
        if (receipt.get("contract_version") != CONTRACT_VERSION or
                receipt.get("quality_check", {}).get("passed") is not True or
                (_model_bound(receipt) and receipt.get("model_verified") is not True)):
            return outcome("unverified", "Image needs current validation")
        return outcome("verified", "Image and inputs match the validated receipt")
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return outcome("unverified", "Image receipt cannot be validated")
