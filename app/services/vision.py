"""Leaf disease classifier with open-set rejection.

Three independent gates decide whether a photo is even a leaf we know:
  1. an explicit "other" class trained on food, pets, flowers and synthetic junk;
  2. Mahalanobis distance of the pooled embedding to the nearest class mean (calibrated on validation data);
  3. softmax confidence and margin on the remaining classes.
Only when all three pass do we name a disease and hand over a protocol.
"""
from __future__ import annotations

import io
import json
import logging
import threading
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from app.config import settings
from app.knowledge import diseases

log = logging.getLogger("farmiq.vision")

_lock = threading.Lock()
_model = None
_labels: list[str] = []
_transform = None
_torch = None
_meta: dict[str, Any] = {}
_ood: dict[str, np.ndarray] | None = None

# Legacy (v1) label names -> canonical crop__condition ids.
LEGACY = {
    "Pepper__bell___Bacterial_spot": "pepper__bacterial_spot", "Pepper__bell___healthy": "pepper__healthy",
    "Potato___Early_blight": "potato__early_blight", "Potato___Late_blight": "potato__late_blight", "Potato___healthy": "potato__healthy",
    "Tomato__Target_Spot": "tomato__target_spot", "Tomato__Tomato_mosaic_virus": "tomato__mosaic_virus", "Tomato__Tomato_YellowLeaf__Curl_Virus": "tomato__yellow_leaf_curl_virus",
    "Tomato_Bacterial_spot": "tomato__bacterial_spot", "Tomato_Early_blight": "tomato__early_blight", "Tomato_healthy": "tomato__healthy",
    "Tomato_Late_blight": "tomato__late_blight", "Tomato_Leaf_Mold": "tomato__leaf_mold", "Tomato_Septoria_leaf_spot": "tomato__septoria_leaf_spot",
    "Tomato_Spider_mites_Two_spotted_spider_mite": "tomato__spider_mites",
}


def _build() -> None:
    global _model, _labels, _transform, _torch, _meta, _ood
    import torch
    import torch.nn as nn
    import torchvision.transforms as T
    from torchvision import models

    meta = json.loads((settings.model_dir / "leaf_meta.json").read_text(encoding="utf-8"))
    arch = meta.get("arch", "mobilenet_v3_small")
    model = models.mobilenet_v3_large(weights=None) if arch == "mobilenet_v3_large" else models.mobilenet_v3_small(weights=None)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(meta["labels"]))
    model.load_state_dict(torch.load(settings.model_dir / "leaf_mobilenetv3.pt", map_location="cpu"))
    model.eval()
    torch.set_num_threads(max(1, torch.get_num_threads() // 2))
    _transform = T.Compose([T.Resize((meta["size"], meta["size"])), T.ToTensor(), T.Normalize(meta["mean"], meta["std"])])
    _labels = [LEGACY.get(x, x) for x in meta["labels"]]
    ood_path = settings.model_dir / "leaf_ood.npz"
    _ood = None
    if ood_path.exists() and meta.get("ood"):
        z = np.load(ood_path)
        _ood = {"means": z["means"], "prec": z["prec"], "thr": float(meta["ood"]["mahalanobis_threshold"])}
    _model, _torch = model, torch
    _meta = {"arch": arch, "size": meta["size"], "val_acc": meta.get("val_acc"), "train_images": meta.get("train_images"), "val_images": meta.get("val_images"),
             "other_index": meta.get("other_index", -1), "ood": meta.get("ood"), "per_class": meta.get("per_class")}
    log.info("vision model %s loaded: %d classes, val_acc=%s, open-set=%s", arch, len(_labels), meta.get("val_acc"), _ood is not None)


def warm() -> None:
    with _lock:
        if _model is None:
            _build()


def ready() -> bool:
    return _model is not None


def info() -> dict[str, Any]:
    return {k: v for k, v in _meta.items() if k != "per_class"} | {"classes": len(_labels), "min_confidence": settings.vision_min_confidence, "tta": "horizontal-flip"}


def crops_covered() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for lab in _labels:
        if "__" in lab:
            crop, cond = lab.split("__", 1)
            out.setdefault(crop, []).append(cond)
    return out


def predict(image_bytes: bytes, top_k: int = 3) -> dict[str, Any]:
    warm()
    torch = _torch
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    x = _transform(image).unsqueeze(0)
    with torch.no_grad():
        f1 = _model.avgpool(_model.features(x)).flatten(1)
        f2 = _model.avgpool(_model.features(torch.flip(x, dims=[3]))).flatten(1)
        logits = (_model.classifier(f1) + _model.classifier(f2)) / 2
        probs = torch.softmax(logits, dim=1)[0].numpy()
        feat = ((f1 + f2) / 2)[0].numpy()

    other = _meta.get("other_index", -1)
    p_other = float(probs[other]) if other is not None and other >= 0 else 0.0
    distance = None
    far = False
    if _ood is not None:
        d = feat[None, :] - _ood["means"]
        md = np.einsum("kd,de,ke->k", d, _ood["prec"], d)
        if other >= 0:
            md[other] = np.inf
        distance = float(np.sqrt(md.min()))
        far = distance > _ood["thr"]

    order = np.argsort(-probs)
    candidates = []
    for i in order:
        if i == other:
            continue
        key = _labels[i]
        info_ = diseases().get(key, {})
        crop, cond = (key.split("__", 1) + [""])[:2]
        candidates.append({
            "id": key,
            "crop": info_.get("crop", crop.replace("_", " ").title()),
            "name": info_.get("name", cond.replace("_", " ").capitalize()),
            "severity": info_.get("severity", "unknown"),
            "confidence": round(float(probs[i]), 4),
        })
        if len(candidates) >= top_k:
            break
    top = candidates[0]
    margin = top["confidence"] - (candidates[1]["confidence"] if len(candidates) > 1 else 0)

    if p_other >= 0.5 or (far and p_other >= 0.15) or (far and top["confidence"] < 0.8):
        verdict = "not_a_leaf"
    elif top["confidence"] < settings.vision_min_confidence or far:
        verdict = "uncertain"
    elif margin >= 0.15 and top["confidence"] >= 0.7:
        verdict = "confident"
    else:
        verdict = "likely"
    protocol = diseases().get(top["id"]) if verdict in ("confident", "likely") else None
    return {
        "verdict": verdict,
        "top": top if verdict != "not_a_leaf" else None,
        "candidates": candidates if verdict != "not_a_leaf" else [],
        "protocol": protocol,
        "gates": {"p_other": round(p_other, 4), "distance": round(distance, 2) if distance is not None else None, "distance_threshold": round(_ood["thr"], 2) if _ood else None, "far": far, "margin": round(margin, 4)},
        "image": {"width": width, "height": height},
        "model": info(),
        "advice": _advice(verdict, top),
    }


def _advice(verdict: str, top: dict[str, Any]) -> str:
    if verdict == "not_a_leaf":
        return "This does not look like a leaf of a crop the scanner knows. Photograph a single leaf filling the frame, in daylight, against a plain background."
    if verdict == "uncertain":
        return "The model is not sure. Retake the photo closer, in daylight, with both a healthy and an affected area of the same leaf in view."
    if top["severity"] == "none":
        return "No disease pattern detected on this leaf. Keep scouting the lower canopy every few days."
    if top["severity"] == "critical":
        return "Treat this as an emergency: act today and re-scan a different leaf tomorrow to confirm the spread is stopped."
    return "Follow the protocol below and re-scan in 5-7 days to check the response."
