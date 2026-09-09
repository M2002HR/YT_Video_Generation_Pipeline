"""Pluggable focal-target resolution for Motion Director.

The production V2 path starts with ChatGPT's image-grounded bounding boxes, optionally
verifies face-like targets with MediaPipe, and always retains a deterministic centre-safe
fallback.  Future open-vocabulary detectors can implement the same provider contract
without changing the director, schema, camera solver, or renderer.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any


def face_detector_status() -> dict[str, Any]:
    available = importlib.util.find_spec("mediapipe") is not None and importlib.util.find_spec("cv2") is not None
    return {"provider": "mediapipe", "available": available, "required": False}

def detect_faces(image: Path) -> list[dict[str, float]]:
    """Return MediaPipe face boxes when installed, otherwise an empty graceful fallback."""
    try:
        import mediapipe as mp  # type: ignore
        import cv2  # type: ignore
    except ImportError:
        return []
    frame=cv2.imread(str(image))
    if frame is None: return []
    h,w=frame.shape[:2]
    with mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=.5) as detector:
        result=detector.process(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
    boxes=[]
    for face in result.detections or []:
        box=face.location_data.relative_bounding_box
        boxes.append({"x":max(0,min(1,box.x+box.width/2)),"y":max(0,min(1,box.y+box.height/2)),"w":max(.01,min(1,box.width)),"h":max(.01,min(1,box.height))})
    return boxes

def snap_face_target(target: dict[str, Any], faces: list[dict[str,float]]) -> tuple[dict[str,Any], bool]:
    """Snap an approximate model face target to a detected face, never force a face guess."""
    if not faces or "face" not in str(target.get("label","")).lower(): return target, False
    chosen=min(faces,key=lambda f:(f["x"]-float(target.get("x",.5)))**2+(f["y"]-float(target.get("y",.5)))**2)
    return {**target, **chosen}, True


def resolve_target(
    target: dict[str, Any] | None,
    image: Path,
    *,
    face_protection: bool = True,
    fallback_label: str = "center-safe fallback",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve one normalized target through a deterministic provider chain.

    Returned coordinates use image-normalized centre ``x/y`` plus bounding-box ``w/h``.
    A future Grounding DINO provider can be inserted before ``fallback_center`` while
    preserving this return contract.
    """
    candidate = dict(target or {})
    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else candidate
    required = ("x", "y", "w", "h")
    if all(key in bbox for key in required):
        normalized = {key: float(bbox[key]) for key in required}
        provider = "chatgpt_bbox"
        if face_protection and candidate.get("kind") in {"face", "person"}:
            faces = detect_faces(image)
            if faces:
                nearest = min(faces, key=lambda face: (face["x"] - normalized["x"]) ** 2 + (face["y"] - normalized["y"]) ** 2)
                if ((nearest["x"] - normalized["x"]) ** 2 + (nearest["y"] - normalized["y"]) ** 2) ** .5 <= .20:
                    normalized = nearest
                    provider = "mediapipe_face"
        return {**candidate, "bbox": normalized}, {"provider": provider, "fallback": False}
    return {
        "target_id": str(candidate.get("target_id") or "fallback_center"),
        "label": str(candidate.get("label") or fallback_label),
        "kind": "context",
        "bbox": {"x": .5, "y": .42, "w": .5, "h": .5},
        "confidence": 0.0,
    }, {"provider": "fallback_center", "fallback": True}
