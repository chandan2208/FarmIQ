"""Prices by region: live Agmarknet for India (with disk cache), curated reference tables elsewhere."""
from __future__ import annotations

import statistics
from typing import Any

import httpx

from app.config import settings
from app.knowledge import BUSHEL_KG, crops, region_for_id
from app.services import cache

BASE = "https://api.data.gov.in/resource/"
TTL = 30 * 60


async def prices(state: str | None = None, district: str | None = None, commodity: str | None = None, limit: int = 300) -> dict[str, Any]:
    key = f"market:{(state or '').lower()}:{(district or '').lower()}:{(commodity or '').lower()}:{limit}"
    hit = cache.get(key, TTL)
    if hit is not None:
        hit["cache"] = "fresh"
        return hit
    params: dict[str, Any] = {"api-key": settings.data_gov_api_key, "format": "json", "limit": limit}
    if state:
        params["filters[state]"] = state.title() if state.islower() else state
    if district:
        params["filters[district]"] = district.title() if district.islower() else district
    if commodity:
        params["filters[commodity]"] = commodity
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s + 10) as client:
            r = await client.get(BASE + settings.agmarknet_resource, params=params)
            r.raise_for_status()
            payload = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        stale = cache.get(key, TTL, allow_stale=True)
        if stale:
            stale["cache"] = "stale"
            stale["age_s"] = cache.age_s(key)
            return stale
        return {"mode": "live", "records": [], "summary": [], "total": 0, "error": f"Agmarknet unavailable: {exc}", "cache": "none"}

    records = []
    for rec in payload.get("records", []):
        try:
            records.append({
                "state": rec.get("state"), "district": rec.get("district"), "market": rec.get("market"),
                "commodity": rec.get("commodity"), "variety": rec.get("variety"), "grade": rec.get("grade"),
                "date": rec.get("arrival_date"),
                "min": float(rec.get("min_price") or 0), "max": float(rec.get("max_price") or 0), "modal": float(rec.get("modal_price") or 0),
            })
        except (TypeError, ValueError):
            continue
    result = {"mode": "live", "records": records, "summary": summarise(records), "total": payload.get("total", len(records)), "cache": "fresh"}
    cache.put(key, result)
    return result


def summarise(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r["modal"] > 0:
            by.setdefault(r["commodity"], []).append(r)
    reference = {v["agmarknet"].lower(): (k, v["price_q"], v["label"]) for k, v in crops().items()}
    out = []
    for name, rows in by.items():
        modals = [r["modal"] for r in rows]
        median = statistics.median(modals)
        ref = reference.get(name.lower())
        signal = None
        if ref:
            delta = (median - ref[1]) / ref[1] * 100
            signal = {"crop": ref[0], "label": ref[2], "reference_q": ref[1], "delta_pct": round(delta, 1)}
        out.append({
            "commodity": name,
            "markets": len({r["market"] for r in rows}),
            "median_modal": round(median),
            "min": round(min(r["min"] for r in rows if r["min"] > 0) if any(r["min"] > 0 for r in rows) else min(modals)),
            "max": round(max(r["max"] for r in rows)),
            "spread_pct": round((max(modals) - min(modals)) / median * 100, 1) if median else 0,
            "best_market": max(rows, key=lambda r: r["modal"])["market"],
            "signal": signal,
        })
    out.sort(key=lambda x: -x["markets"])
    return out


def reference(region_id: str) -> dict[str, Any]:
    """Curated farm-gate reference prices for a region, in local currency and local trade units."""
    region = region_for_id(region_id)
    rows = []
    for cid in region["crops"]:
        k = crops().get(cid)
        if not k:
            continue
        if region["id"] == "IN":
            price_t = k["price_t"]
        else:
            price_t = region.get("prices_t", {}).get(cid)
        if price_t is None:
            continue
        local_unit, local_price = "t", price_t
        if region["units"] == "india":
            local_unit, local_price = "quintal", price_t / 10
        elif region["units"] == "us":
            bu = BUSHEL_KG.get(cid)
            if bu:
                local_unit, local_price = "bu", price_t * bu / 1000
            else:
                local_unit, local_price = "ton", price_t * 0.907
        rows.append({
            "crop": cid, "label": k["label"], "category": k["category"],
            "price_t": round(price_t, 2), "local_price": round(local_price, 2), "local_unit": local_unit,
            "cost_ha": (region.get("costs_ha", {}).get(cid) if region["id"] != "IN" else k["cost_ha"]),
            "yield_potential": (region.get("yield_potential", {}).get(cid) if region["id"] != "IN" else k["yield_potential"]),
        })
    rows.sort(key=lambda r: r["label"])
    return {"mode": "reference", "region": {k: region[k] for k in ("id", "name", "currency", "symbol", "units", "sources")}, "rows": rows}


def commodity_for(crop_id: str) -> str | None:
    info = crops().get(crop_id)
    return info["agmarknet"] if info else None
