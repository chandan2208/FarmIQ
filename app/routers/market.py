from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import market

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/prices")
async def prices(
    state: str | None = Query(None, max_length=60),
    district: str | None = Query(None, max_length=60),
    commodity: str | None = Query(None, max_length=80),
    crop: str | None = Query(None, max_length=40),
    limit: int = Query(300, ge=10, le=1000),
):
    """Live Agmarknet prices (India)."""
    if crop and not commodity:
        commodity = market.commodity_for(crop)
    return await market.prices(state=state, district=district, commodity=commodity, limit=limit)


@router.get("/reference")
def reference(region: str = Query("WORLD", max_length=8)):
    """Curated farm-gate reference prices for a region (US, UK, EU, IN, WORLD)."""
    return market.reference(region.upper())
