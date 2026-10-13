"""16-day forecast with field-level derivatives: soil moisture by depth, spray windows, disease pressure."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.knowledge import diseases
from app.services import cache

FORECAST = "https://api.open-meteo.com/v1/forecast"
TTL = 45 * 60


async def forecast(lat: float, lon: float) -> dict[str, Any]:
    key = f"forecast:{lat:.3f}:{lon:.3f}"
    hit = cache.get(key, TTL)
    if hit is not None:
        return hit
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 16,
        "daily": ",".join([
            "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "precipitation_probability_max",
            "et0_fao_evapotranspiration", "wind_speed_10m_max", "shortwave_radiation_sum", "sunshine_duration",
            "weather_code",
        ]),
        "hourly": ",".join([
            "temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m",
            "soil_moisture_0_to_1cm", "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm", "soil_moisture_27_to_81cm",
            "soil_temperature_6cm",
        ]),
        "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code,is_day",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            r = await client.get(FORECAST, params=params)
            r.raise_for_status()
            raw = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        stale = cache.get(key, TTL, allow_stale=True)
        if stale:
            stale["stale"] = True
            return stale
        raise RuntimeError(f"Open-Meteo forecast unavailable: {exc}") from exc

    result = _shape(raw)
    cache.put(key, result)
    return result


def _shape(raw: dict[str, Any]) -> dict[str, Any]:
    d, h = raw["daily"], raw["hourly"]
    hours = h["time"]
    by_day: dict[str, list[int]] = {}
    for i, t in enumerate(hours):
        by_day.setdefault(t[:10], []).append(i)

    days = []
    for i, day in enumerate(d["time"]):
        idx = by_day.get(day, [])
        rh = [h["relative_humidity_2m"][j] for j in idx if h["relative_humidity_2m"][j] is not None]
        rh_mean = round(sum(rh) / len(rh), 0) if rh else None
        wet_hours = sum(1 for j in idx if (h["relative_humidity_2m"][j] or 0) >= 85)
        sm = _mean([h["soil_moisture_3_to_9cm"][j] for j in idx])
        tmax, tmin = d["temperature_2m_max"][i], d["temperature_2m_min"][i]
        rain_day = d["precipitation_sum"][i] or 0.0
        sm_deep = _mean([h["soil_moisture_9_to_27cm"][j] for j in idx])
        days.append({
            "date": day,
            "tmax": tmax,
            "tmin": tmin,
            "frost": tmin is not None and tmin <= 0,
            "chill": tmin is not None and 0 < tmin <= 4,
            "gdd10": round(max(0.0, ((tmax or 0) + (tmin or 0)) / 2 - 10), 1),
            # Machinery can travel when the 9-27 cm layer is below ~field capacity and the day is dry.
            "workable": sm_deep is not None and sm_deep < 0.33 and rain_day < 2 and not (tmin is not None and tmin <= 0),
            "rain": rain_day,
            "rain_prob": d["precipitation_probability_max"][i],
            "et0": d["et0_fao_evapotranspiration"][i],
            "wind_max": d["wind_speed_10m_max"][i],
            "radiation": d["shortwave_radiation_sum"][i],
            "sunshine_h": round((d["sunshine_duration"][i] or 0) / 3600, 1),
            "code": d["weather_code"][i],
            "rh_mean": rh_mean,
            "wet_hours": wet_hours,
            "soil_moisture": round(sm, 3) if sm is not None else None,
            "spray_windows": _spray_windows(h, idx),
        })

    soil_profile = {
        "0_1cm": _mean(h["soil_moisture_0_to_1cm"][:24]),
        "3_9cm": _mean(h["soil_moisture_3_to_9cm"][:24]),
        "9_27cm": _mean(h["soil_moisture_9_to_27cm"][:24]),
        "27_81cm": _mean(h["soil_moisture_27_to_81cm"][:24]),
        "soil_temp_6cm": _mean(h["soil_temperature_6cm"][:24]),
    }
    return {
        "lat": raw["latitude"], "lon": raw["longitude"], "elevation": raw.get("elevation"),
        "timezone": raw.get("timezone"),
        "current": raw.get("current"),
        "days": days,
        "soil_profile": {k: (round(v, 3) if v is not None else None) for k, v in soil_profile.items()},
        "summary": {
            "rain_7d": round(sum(x["rain"] for x in days[:7]), 1),
            "rain_16d": round(sum(x["rain"] for x in days), 1),
            "frost_nights": sum(1 for x in days if x["frost"]),
            "first_frost": next((x["date"] for x in days if x["frost"]), None),
            "gdd10_16d": round(sum(x["gdd10"] for x in days)),
            "workable_days": sum(1 for x in days if x["workable"]),
            "next_workable": next((x["date"] for x in days if x["workable"]), None),
            "heat_days_35": sum(1 for x in days if (x["tmax"] or 0) >= 35),
        },
        "hourly": {
            "time": hours[:72],
            "temp": h["temperature_2m"][:72],
            "rh": h["relative_humidity_2m"][:72],
            "rain": h["precipitation"][:72],
            "wind": h["wind_speed_10m"][:72],
        },
        "fetched_at": datetime.now().isoformat(timespec="minutes"),
    }


def _mean(values: list[float | None]) -> float | None:
    xs = [v for v in values if v is not None]
    return sum(xs) / len(xs) if xs else None


def _spray_windows(h: dict[str, Any], idx: list[int]) -> list[dict[str, Any]]:
    """Hours safe for foliar spraying: light wind, dry, humidity below drift/runoff thresholds, daytime."""
    windows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for j in idx:
        hour = int(h["time"][j][11:13])
        wind = h["wind_speed_10m"][j] or 0
        rain_next = sum((h["precipitation"][k] or 0) for k in range(j, min(j + 6, len(h["precipitation"]))))
        rh = h["relative_humidity_2m"][j] or 0
        ok = 6 <= hour <= 18 and wind <= 15 and rain_next < 0.5 and 40 <= rh <= 85
        if ok and current is None:
            current = {"start": h["time"][j][11:16], "end": None, "hours": 0}
        if ok and current is not None:
            current["hours"] += 1
            current["end"] = f"{hour + 1:02d}:00"
        if not ok and current is not None:
            if current["hours"] >= 2:
                windows.append(current)
            current = None
    if current is not None and current["hours"] >= 2:
        windows.append(current)
    return windows


CROP_ALIAS = {"maize": "corn", "sweet_corn": "corn", "chillies": "pepper", "canola": None, "mustard": None}


def disease_pressure(days: list[dict[str, Any]], crop: str | None = None) -> list[dict[str, Any]]:
    """Score each known disease 0-100 on how well the next 7 days suit it; the twin's crop is listed first."""
    week = days[:7]
    prefix = CROP_ALIAS.get(crop, crop) if crop else None
    out = []
    for key, info in diseases().items():
        fav = info.get("favoured_by")
        if not fav:
            continue
        scores = []
        for day in week:
            tmean = (day["tmax"] + day["tmin"]) / 2
            lo, hi = fav["temp"]
            t_score = 1.0 if lo <= tmean <= hi else max(0.0, 1 - min(abs(tmean - lo), abs(tmean - hi)) / 6)
            rh_score = 1.0 if fav["humidity_min"] == 0 else min(1.0, (day["rh_mean"] or 0) / fav["humidity_min"])
            if fav["rain"]:
                wet_score = min(1.0, day["wet_hours"] / 8) if day["rain"] < 1 else 1.0
            else:
                wet_score = 1.0 if day["rain"] < 1 else 0.4
            scores.append(t_score * rh_score * wet_score)
        pressure = round(100 * sum(scores) / len(scores)) if scores else 0
        mine = bool(prefix) and key.startswith(prefix + "__")
        out.append({"id": key, "crop": info["crop"], "name": info["name"], "severity": info["severity"], "pressure": pressure, "mine": mine})
    out.sort(key=lambda x: (not x["mine"], -x["pressure"]))
    return out
