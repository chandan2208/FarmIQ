"""Digital twin endpoints: simulate one scenario, compare several, and find the best sowing window for every crop."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.knowledge import SOIL_LABELS, crops, economics_for, region_for, regions, season_label
from app.services import cache, site, weather
from app.services.simulator import SimInput, build_series, simulate

router = APIRouter(prefix="/api/twin", tags=["twin"])

Texture = Literal["sandy", "sandyloam", "loamy", "alluvial", "red", "laterite", "clay", "black"]
Irrigation = Literal["rainfed", "limited", "full"]


class Scenario(BaseModel):
    crop: str
    sow_date: date
    area_ha: float = Field(1.0, gt=0, le=100000)
    irrigation: Irrigation = "limited"
    n_applied_kg_ha: float | None = Field(None, ge=0, le=600)
    price_t: float | None = Field(None, gt=0, description="local currency per tonne")
    cost_ha: float | None = Field(None, ge=0, description="local currency per hectare")


class SoilOverride(BaseModel):
    texture: Texture | None = None
    ph: float | None = Field(None, ge=3.5, le=10)
    n_credit_kg_ha: float | None = Field(None, ge=0, le=400)


class SimulateRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    country: str | None = Field(None, max_length=2)
    scenario: Scenario
    soil: SoilOverride | None = None


class CompareRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    country: str | None = Field(None, max_length=2)
    scenarios: list[Scenario] = Field(..., min_length=1, max_length=8)
    soil: SoilOverride | None = None


class RankRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    country: str | None = Field(None, max_length=2)
    area_ha: float = Field(1.0, gt=0, le=100000)
    irrigation: Irrigation = "limited"
    all_crops: bool = False
    soil: SoilOverride | None = None


async def _inputs(lat: float, lon: float, country_code: str | None):
    try:
        tasks = [site.soil(lat, lon), site.climate(lat, lon), weather.forecast(lat, lon)]
        if not country_code:
            tasks.append(site.country(lat, lon))
        results = await asyncio.gather(*tasks)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Upstream data unavailable: {exc}") from exc
    soil, clim, fc = results[0], results[1], results[2]
    cc = country_code or (results[3]["country_code"] if len(results) > 3 else None)
    return soil, clim, fc, region_for(cc)


def _sim_input(sc: Scenario, soil: dict, override: SoilOverride | None, clim: dict, fc: dict, region: dict) -> SimInput:
    if sc.crop not in crops():
        raise HTTPException(422, f"Unknown crop '{sc.crop}'")
    texture = override.texture if override and override.texture else soil["texture"]
    ph = override.ph if override and override.ph is not None else soil["ph"]
    n_credit = override.n_credit_kg_ha if override and override.n_credit_kg_ha is not None else soil["n_credit_kg_ha"]
    # Long enough for autumn-sown crops to overwinter; the simulation stops at maturity or frost kill anyway.
    horizon = max(int(crops()[sc.crop]["duration_days"] * 1.35) + 10, 400)
    series = build_series(sc.sow_date, horizon, fc["days"], clim["days"])
    eco = economics_for(sc.crop, region)
    fx = {"INR": 1.0, "USD": 1 / 84.0, "GBP": 1 / 106.0, "EUR": 1 / 91.0}.get(region["currency"], 1.0)
    return SimInput(
        crop=sc.crop, sow_date=sc.sow_date, area_ha=sc.area_ha, texture=texture, ph=ph, n_credit_kg_ha=n_credit,
        n_applied_kg_ha=sc.n_applied_kg_ha, irrigation=sc.irrigation,
        price_t=sc.price_t or eco["price_t"], cost_ha=sc.cost_ha or eco["cost_ha"], yield_potential=eco["yield_potential"],
        currency=eco["currency"], irrigation_cost_mm_ha=25.0 * fx, weather=series,
    )


def _site_block(soil, clim, region):
    return {"soil": soil, "climate": {k: v for k, v in clim.items() if k != "days"}, "region": region}


@router.post("/simulate")
async def simulate_one(req: SimulateRequest):
    soil, clim, fc, region = await _inputs(req.lat, req.lon, req.country)
    result = simulate(_sim_input(req.scenario, soil, req.soil, clim, fc, region))
    result["season"] = season_label(req.scenario.sow_date, region, req.lat)
    result["site"] = _site_block(soil, clim, region)
    return result


@router.post("/compare")
async def compare(req: CompareRequest):
    soil, clim, fc, region = await _inputs(req.lat, req.lon, req.country)
    results = [simulate(_sim_input(sc, soil, req.soil, clim, fc, region)) for sc in req.scenarios]
    for r in results:
        r["daily"] = r["daily"][:: max(1, len(r["daily"]) // 60)]
    return {"results": results, "region": region}


@router.post("/rank")
async def rank(req: RankRequest):
    """Sowing-window finder: simulate each crop at candidate sowing dates through the coming year and keep the best."""
    soil, clim, fc, region = await _inputs(req.lat, req.lon, req.country)
    key = f"rank:{req.lat:.3f}:{req.lon:.3f}:{region['id']}:{req.irrigation}:{req.area_ha}:{req.all_crops}:{req.soil.model_dump_json() if req.soil else ''}:{date.today()}"
    hit = cache.get(key, 6 * 3600)
    if hit is not None:
        return hit
    today = date.today()
    all_candidates = [today - timedelta(days=90) + timedelta(days=15 * i) for i in range(0, 25)]  # ~ one year ahead, recent past included
    crop_ids = list(crops()) if req.all_crops else [c for c in region["crops"] if c in crops()]
    calendar = region.get("sowing", {})
    india_seasons = {"kharif": [6, 7], "rabi": [10, 11, 12], "zaid": [2, 3]}
    rows: list[dict[str, Any]] = []
    for cid in crop_ids:
        k = crops()[cid]
        months = calendar.get(cid)
        if not months and region["id"] == "IN":
            months = sorted({m for s in k["seasons"] for m in india_seasons.get(s, [])})
        if months and req.lat < 0:
            months = [((m + 5) % 12) + 1 for m in months]  # southern hemisphere: shift six months
        candidates = [c for c in all_candidates if not months or c.month in months] or all_candidates
        best: dict[str, Any] | None = None
        windows: list[dict[str, Any]] = []
        for sow in candidates:
            sc = Scenario(crop=cid, sow_date=sow, area_ha=req.area_ha, irrigation=req.irrigation)
            r = simulate(_sim_input(sc, soil, req.soil, clim, fc, region))
            entry = {"sow_date": sow.isoformat(), "season": season_label(sow, region, req.lat), "matured": bool(r["matured_on"]), "yield_t_ha": r["yield_t_ha"], "net": r["economics"]["net"], "suitability": r["suitability"], "irrigation_mm": r["water"]["irrigation_mm"]}
            windows.append(entry)
            if best is None or (entry["matured"], entry["net"], entry["suitability"]) > (best["entry"]["matured"], best["entry"]["net"], best["entry"]["suitability"]):
                best = {"entry": entry, "result": r}
        assert best is not None
        r = best["result"]
        # Contiguous span of candidate dates around the best one that stay within 15% of its margin and still mature.
        bi = windows.index(best["entry"])
        ok = lambda w: w["matured"] and w["net"] >= 0.85 * best["entry"]["net"]  # noqa: E731
        lo = bi
        while lo - 1 >= 0 and ok(windows[lo - 1]):
            lo -= 1
        hi = bi
        while hi + 1 < len(windows) and ok(windows[hi + 1]):
            hi += 1
        good = windows[lo:hi + 1] if ok(best["entry"]) else []
        haircut = {"vegetable": 0.6, "spice": 0.65, "cash": 0.85, "forage": 0.9}.get(k["category"], 1.0)
        rows.append({
            "crop": cid, "label": k["label"], "category": k["category"], "water": k["water"],
            "sow_date": best["entry"]["sow_date"], "season": best["entry"]["season"], "matured": best["entry"]["matured"], "matured_on": r["matured_on"], "days": r["days"],
            "suitability": r["suitability"], "yield_t_ha": r["yield_t_ha"], "yield_potential_t_ha": r["yield_potential_t_ha"],
            "net": r["economics"]["net"], "risk_adjusted_net": round(r["economics"]["net"] * haircut) if r["economics"]["net"] > 0 else r["economics"]["net"], "market_haircut": haircut,
            "roi_pct": r["economics"]["roi_pct"], "revenue": r["economics"]["revenue"], "cost": r["economics"]["cost"],
            "irrigation_mm": r["water"]["irrigation_mm"], "factors": r["factors"], "top_risk": r["risks"][0]["text"] if r["risks"] else None,
            "window": {"from": good[0]["sow_date"], "to": good[-1]["sow_date"]} if good else None,
            "windows": windows,
        })
    rows.sort(key=lambda x: (x["matured"], x["risk_adjusted_net"], x["suitability"]), reverse=True)
    out = {
        "area_ha": req.area_ha, "irrigation": req.irrigation, "currency": region["currency"],
        "candidates": [c.isoformat() for c in all_candidates],
        "site": _site_block(soil, clim, region), "ranking": rows,
    }
    cache.put(key, out)
    return out


@router.get("/crops")
def crop_catalogue():
    out = []
    for cid, k in crops().items():
        out.append({
            "id": cid, "label": k["label"], "category": k["category"], "seasons": k["seasons"], "duration_days": k["duration_days"],
            "water": k["water"], "price_t": k["price_t"], "cost_ha": k["cost_ha"], "yield_potential": k["yield_potential"], "bu_kg": k["bu_kg"],
            "n_kg_ha": k["n_kg_ha"], "t_opt": k["t_opt"], "rain_opt": k["rain_opt"], "ph_opt": k["ph_opt"], "soils": k["soils"], "tips": k["tips"],
        })
    return {"crops": out, "textures": SOIL_LABELS, "regions": regions()}
