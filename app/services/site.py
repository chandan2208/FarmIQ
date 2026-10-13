"""Site profile for a plot: satellite-derived soil (ISRIC SoilGrids) + reanalysis climate (Open-Meteo archive)."""
from __future__ import annotations

import asyncio
import statistics
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import settings
from app.knowledge import SOIL_LABELS, region_for, texture_from_fractions
from app.services import cache

SOILGRIDS = "https://rest.isric.org/soilgrids/v2.0/properties/query"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

ARCHIVE_TTL = 7 * 24 * 3600
SOIL_TTL = 90 * 24 * 3600


async def geocode(query: str, count: int = 6) -> list[dict[str, Any]]:
    key = f"geo:{query.lower().strip()}:{count}"
    hit = cache.get(key, 30 * 24 * 3600)
    if hit is not None:
        return hit
    async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
        r = await client.get(GEOCODE, params={"name": query, "count": count, "language": "en", "format": "json"})
        r.raise_for_status()
        found = r.json().get("results", [])
        # "Ames Iowa" or "Lincoln, England": retry with the place name alone and prefer matches in the named region.
        words = [w for w in query.replace(",", " ").split() if w]
        if not found and len(words) >= 2:
            hint = " ".join(words[1:]).lower()
            r2 = await client.get(GEOCODE, params={"name": words[0], "count": 20, "language": "en", "format": "json"})
            if r2.status_code == 200:
                cands = r2.json().get("results", [])
                found = [x for x in cands if hint in " ".join(str(x.get(k, "")) for k in ("admin1", "admin2", "country")).lower()] or cands[:count]
        results = [
            {
                "name": x.get("name"),
                "admin1": x.get("admin1"),
                "admin2": x.get("admin2"),
                "country": x.get("country"),
                "country_code": x.get("country_code"),
                "region": region_for(x.get("country_code"))["id"],
                "lat": x.get("latitude"),
                "lon": x.get("longitude"),
                "elevation": x.get("elevation"),
            }
            for x in found[:count]
        ]
    cache.put(key, results)
    return results


async def soil(lat: float, lon: float) -> dict[str, Any]:
    key = f"soil:{lat:.3f}:{lon:.3f}"
    hit = cache.get(key, SOIL_TTL)
    if hit is not None:
        return hit
    params = [
        ("lon", lon), ("lat", lat),
        ("property", "phh2o"), ("property", "nitrogen"), ("property", "clay"), ("property", "sand"),
        ("property", "soc"), ("property", "cec"), ("property", "bdod"),
        ("depth", "0-5cm"), ("depth", "5-15cm"), ("depth", "15-30cm"), ("value", "mean"),
    ]
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s + 15) as client:
            r = await client.get(SOILGRIDS, params=params)
            r.raise_for_status()
            layers = r.json()["properties"]["layers"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        stale = cache.get(key, SOIL_TTL, allow_stale=True)
        if stale:
            stale["source"] = "cached"
            return stale
        return _soil_fallback(str(exc))

    values: dict[str, float] = {}
    for layer in layers:
        name = layer["name"]
        factor = layer["unit_measure"]["d_factor"]
        depth_vals = [d["values"].get("mean") for d in layer["depths"] if d["values"].get("mean") is not None]
        if depth_vals:
            values[name] = statistics.fmean(depth_vals) / factor

    ph = round(values.get("phh2o", 6.8), 2)
    sand = round(values.get("sand", 40.0), 1)
    clay = round(values.get("clay", 20.0), 1)
    silt = round(max(0.0, 100 - sand - clay), 1)
    total_n_gkg = values.get("nitrogen", 1.2)
    bulk = values.get("bdod", 1.35)  # kg/dm3
    soil_mass_kg_ha = bulk * 1000 * 0.15 * 10000  # 15 cm layer, kg per hectare
    # Roughly 2% of total N mineralises in a season; that is the crop-available credit.
    n_credit = round(total_n_gkg * soil_mass_kg_ha / 1000 * 0.02, 1)
    soc = values.get("soc", 8.0)
    texture = texture_from_fractions(sand, clay)
    profile = {
        "source": "soilgrids",
        "ph": ph,
        "sand_pct": sand,
        "silt_pct": silt,
        "clay_pct": clay,
        "texture": texture,
        "texture_label": SOIL_LABELS[texture],
        "organic_carbon_gkg": round(soc, 1),
        "total_nitrogen_gkg": round(total_n_gkg, 2),
        "n_credit_kg_ha": n_credit,
        "cec_cmol_kg": round(values.get("cec", 15.0), 1),
        "bulk_density": round(bulk, 2),
        "notes": _soil_notes(ph, soc, texture),
    }
    cache.put(key, profile)
    return profile


def _soil_fallback(reason: str) -> dict[str, Any]:
    return {
        "source": "default",
        "error": f"SoilGrids unavailable: {reason}",
        "ph": 6.8, "sand_pct": 40.0, "silt_pct": 40.0, "clay_pct": 20.0,
        "texture": "loamy", "texture_label": "Loam", "organic_carbon_gkg": 8.0,
        "total_nitrogen_gkg": 1.2, "n_credit_kg_ha": 45.0, "cec_cmol_kg": 15.0, "bulk_density": 1.35,
        "notes": ["Soil values are generic defaults; edit them from a soil test card."],
    }


def _soil_notes(ph: float, soc: float, texture: str) -> list[str]:
    notes = []
    if ph < 5.5:
        notes.append("Acidic soil: liming at 2-4 t/ha would open up pulses and wheat.")
    elif ph > 8.3:
        notes.append("Alkaline soil: gypsum and organic matter improve structure; prefer barley, mustard, guar.")
    if soc < 5:
        notes.append("Very low organic carbon: add 5-10 t/ha farmyard manure or green manure before sowing.")
    elif soc > 15:
        notes.append("Good organic carbon: nitrogen mineralisation will carry part of the crop's demand.")
    if texture in {"clay", "black"}:
        notes.append("Heavy soil: ridge or raised-bed sowing avoids waterlogging in kharif.")
    elif texture == "sandy":
        notes.append("Light soil: split fertiliser doses and irrigate little and often.")
    return notes


async def climate(lat: float, lon: float) -> dict[str, Any]:
    """Daily series for the last 365 days plus a 12-month climatology."""
    key = f"climate:{lat:.3f}:{lon:.3f}"
    hit = cache.get(key, ARCHIVE_TTL)
    if hit is not None:
        return hit
    end = date.today() - timedelta(days=6)
    start = end - timedelta(days=365)
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration",
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s + 10) as client:
            r = await client.get(ARCHIVE, params=params)
            r.raise_for_status()
            d = r.json()["daily"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        stale = cache.get(key, ARCHIVE_TTL, allow_stale=True)
        if stale:
            return stale
        raise RuntimeError(f"Open-Meteo archive unavailable: {exc}") from exc

    days = []
    for i, day in enumerate(d["time"]):
        tmax, tmin = d["temperature_2m_max"][i], d["temperature_2m_min"][i]
        if tmax is None or tmin is None:
            continue
        days.append({
            "date": day,
            "tmax": tmax,
            "tmin": tmin,
            "rain": d["precipitation_sum"][i] or 0.0,
            "et0": d["et0_fao_evapotranspiration"][i] or _hargreaves(tmax, tmin),
        })
    months: dict[int, dict[str, list[float]]] = {m: {"t": [], "r": []} for m in range(1, 13)}
    for x in days:
        m = int(x["date"][5:7])
        months[m]["t"].append((x["tmax"] + x["tmin"]) / 2)
        months[m]["r"].append(x["rain"])
    climatology = [
        {
            "month": m,
            "temp_mean": round(statistics.fmean(v["t"]), 1) if v["t"] else None,
            "rain_mm": round(sum(v["r"]), 0),
        }
        for m, v in months.items()
    ]
    result = {
        "source": "open-meteo-archive",
        "days": days,
        "annual_rain_mm": round(sum(x["rain"] for x in days)),
        "temp_mean": round(statistics.fmean((x["tmax"] + x["tmin"]) / 2 for x in days), 1),
        "climatology": climatology,
    }
    cache.put(key, result)
    return result


def _hargreaves(tmax: float, tmin: float, ra: float = 30.0) -> float:
    tmean = (tmax + tmin) / 2
    return max(0.5, 0.0023 * ra * 0.408 * (tmean + 17.8) * max(tmax - tmin, 1) ** 0.5)


REVERSE = "https://api.bigdatacloud.net/data/reverse-geocode-client"


async def country(lat: float, lon: float) -> dict[str, Any]:
    """Country and locality for a point (free reverse geocoder, no key). Falls back to unknown."""
    key = f"country:{lat:.2f}:{lon:.2f}"
    hit = cache.get(key, 365 * 24 * 3600)
    if hit is not None:
        return hit
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            r = await client.get(REVERSE, params={"latitude": lat, "longitude": lon, "localityLanguage": "en"})
            r.raise_for_status()
            d = r.json()
        out = {"country_code": d.get("countryCode") or None, "country": d.get("countryName"), "admin1": d.get("principalSubdivision"), "locality": d.get("locality") or d.get("city")}
    except (httpx.HTTPError, ValueError):
        out = {"country_code": None, "country": None, "admin1": None, "locality": None}
    cache.put(key, out)
    return out


async def profile(lat: float, lon: float, country_code: str | None = None) -> dict[str, Any]:
    tasks = [soil(lat, lon), climate(lat, lon)]
    if not country_code:
        tasks.append(country(lat, lon))
    results = await asyncio.gather(*tasks)
    s, c = results[0], results[1]
    place = results[2] if len(results) > 2 else {"country_code": country_code}
    region = region_for(place.get("country_code") or country_code)
    return {
        "lat": lat, "lon": lon,
        "place": place,
        "region": region,
        "soil": s,
        "climate": {k: v for k, v in c.items() if k != "days"},
    }
