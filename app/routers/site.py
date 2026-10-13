from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.knowledge import regions
from app.services import site

router = APIRouter(prefix="/api/site", tags=["site"])


@router.get("/geocode")
async def geocode(q: str = Query(..., min_length=2, max_length=80)):
    try:
        return {"results": await site.geocode(q)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Geocoding unavailable: {exc}") from exc


@router.get("/profile")
async def profile(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), country: str | None = Query(None, max_length=2)):
    try:
        return await site.profile(lat, lon, country)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc


@router.get("/regions")
def list_regions():
    return {"regions": regions()}
