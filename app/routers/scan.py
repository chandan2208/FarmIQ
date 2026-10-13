from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.knowledge import diseases
from app.services import vision

router = APIRouter(prefix="/api/scan", tags=["scan"])
MAX_BYTES = 12 * 1024 * 1024


@router.post("/leaf")
async def scan_leaf(file: UploadFile = File(...)):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}:
        raise HTTPException(415, "Upload a JPEG, PNG or WebP photo of a single leaf.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Photo larger than 12 MB; resize it and try again.")
    try:
        return await asyncio.get_running_loop().run_in_executor(None, vision.predict, data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Could not analyse the photo: {exc}") from exc


@router.get("/diseases")
def catalogue():
    return {"diseases": [{"id": k, **v} for k, v in diseases().items()]}


@router.get("/coverage")
def coverage():
    vision.warm()
    return {"crops": vision.crops_covered(), "model": vision.info()}
