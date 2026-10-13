from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services import weather

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.get("/forecast")
async def forecast(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), crop: str | None = Query(None, max_length=40)):
    try:
        data = dict(await weather.forecast(lat, lon))
        data["disease_pressure"] = weather.disease_pressure(data["days"], crop)
        return data
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
