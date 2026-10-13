"""
Season simulator: a daily crop-soil-weather model for one plot.

Growth is driven by growing-degree-days, water by an FAO-56 root-zone bucket with
crop coefficients, yield by FAO-33 stage-wise yield-response factors, then
nutrient, pH, temperature and texture multipliers. Every input is explicit so
the same engine powers "what if" scenarios in the digital twin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.knowledge import SOIL_WATER, crop as crop_info, trapezoid

STAGES = ("ini", "dev", "mid", "late")
STAGE_LABEL = {"ini": "Establishment", "dev": "Vegetative", "mid": "Flowering and fill", "late": "Ripening"}
KY_KEY = {"ini": "veg", "dev": "veg", "mid": "flower", "late": "ripen"}
IRRIGATION_COST_PER_MM_HA = 25.0  # INR, pumped groundwater


@dataclass
class Day:
    date: str
    tmax: float
    tmin: float
    rain: float
    et0: float
    source: str = "climatology"


@dataclass
class SimInput:
    crop: str
    sow_date: date
    area_ha: float = 1.0
    texture: str = "loamy"
    ph: float = 6.8
    n_credit_kg_ha: float = 40.0
    n_applied_kg_ha: float | None = None
    irrigation: str = "limited"  # rainfed | limited | full
    price_t: float | None = None          # local currency per tonne
    cost_ha: float | None = None          # local currency per hectare
    yield_potential: float | None = None  # regional attainable yield, t/ha
    currency: str = "INR"
    irrigation_cost_mm_ha: float = IRRIGATION_COST_PER_MM_HA
    weather: list[Day] = field(default_factory=list)


def build_series(sow: date, horizon_days: int, forecast_days: list[dict], archive_days: list[dict]) -> list[Day]:
    """Stitch observed past, forecast, and same-date-last-year climatology into one daily series."""
    fc = {d["date"]: d for d in forecast_days}
    ar = {d["date"]: d for d in archive_days}
    series: list[Day] = []
    for i in range(horizon_days):
        day = sow + timedelta(days=i)
        iso = day.isoformat()
        if iso in fc and fc[iso].get("tmax") is not None and fc[iso].get("tmin") is not None:
            src, row = "forecast", fc[iso]
        elif iso in ar and ar[iso].get("tmax") is not None and ar[iso].get("tmin") is not None:
            src, row = "observed", ar[iso]
        else:
            # climatology: 7-day smoothed window around the same date one year earlier (or later if sowing far ahead)
            row = _climatology(day, ar)
            src = "climatology"
        series.append(Day(iso, float(row["tmax"]), float(row["tmin"]), float(row.get("rain") or 0.0), float(row.get("et0") or 3.5), src))
    return series


def _climatology(day: date, archive: dict[str, dict]) -> dict[str, float]:
    if not archive:
        return {"tmax": 32.0, "tmin": 20.0, "rain": 2.0, "et0": 4.0}
    tmax = tmin = rain = et0 = 0.0
    n = 0
    for shift in (-365, 365, -730):
        for offset in range(-3, 4):
            iso = (day + timedelta(days=shift + offset)).isoformat()
            row = archive.get(iso)
            if row:
                tmax += row["tmax"]; tmin += row["tmin"]; rain += row.get("rain") or 0.0; et0 += row.get("et0") or 3.5
                n += 1
        if n:
            break
    if not n:
        # sow date beyond archive coverage: fall back to nearest month in archive by day-of-year distance
        best = min(archive.values(), key=lambda r: abs(int(r["date"][5:7]) - day.month) * 31 + abs(int(r["date"][8:10]) - day.day))
        return {"tmax": best["tmax"], "tmin": best["tmin"], "rain": best.get("rain") or 0.0, "et0": best.get("et0") or 3.5}
    return {"tmax": tmax / n, "tmin": tmin / n, "rain": rain / n, "et0": et0 / n}


def simulate(inp: SimInput) -> dict[str, Any]:
    k = crop_info(inp.crop)
    fc, wp = SOIL_WATER.get(inp.texture, SOIL_WATER["loamy"])
    gdd_total = float(k["gdd"])
    bounds = _stage_bounds(k["stage_frac"])
    kc = k["kc"]
    z_max = float(k["root_depth_m"])
    z_min = 0.15

    # state
    gdd = 0.0
    dr = 0.2 * 1000 * (fc - wp) * z_min  # start slightly depleted
    daily: list[dict[str, Any]] = []
    stage_eta: dict[str, float] = {s: 0.0 for s in STAGES}
    stage_etc: dict[str, float] = {s: 0.0 for s in STAGES}
    irrigation_mm = 0.0
    rain_mm = 0.0
    heat_days = cold_days = waterlog_days = dry_spell = longest_dry = 0
    matured_on: str | None = None
    killed_on: str | None = None
    temp_samples: list[float] = []
    frac = 0.0
    # Hardy crops (winter cereals, canola, beans, peas) overwinter; cold nights in the vegetative phase are dormancy, not damage.
    hardy = k["t_abs"][0] <= 4
    kill_temp = -20.0 if hardy else min(k["t_abs"][0] - 6.0, 0.0)
    kill_needed = 3 if hardy else 1
    kill_streak = 0

    for i, w in enumerate(inp.weather):
        tmean = (w.tmax + w.tmin) / 2
        temp_samples.append(tmean)
        gdd += max(0.0, min(tmean, k["t_abs"][1]) - k["t_base"])
        frac = min(1.0, gdd / gdd_total)
        stage = _stage(frac, bounds)
        kc_day = _kc(frac, bounds, kc)
        zr = z_min + (z_max - z_min) * min(1.0, frac / max(bounds["dev"], 1e-6))
        taw = 1000 * (fc - wp) * zr
        etc = kc_day * w.et0
        p = min(0.8, max(0.1, 0.5 + 0.04 * (5 - etc)))
        raw = p * taw
        dr = min(dr, taw)
        ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / max(taw - raw, 1e-6))
        eta = ks * etc

        eff_rain = w.rain if w.rain <= 5 else 5 + (w.rain - 5) * 0.75
        irr = 0.0
        if inp.irrigation != "rainfed" and dr > raw and frac < 0.95:
            target = raw * 0.5 if inp.irrigation == "limited" else 0.0
            irr = max(0.0, dr - target)
        dr = dr - eff_rain - irr + eta
        drained = 0.0
        if dr < 0:
            drained = -dr
            dr = 0.0
        if w.rain > 40 and inp.texture in {"clay", "black"}:
            waterlog_days += 1
        if w.rain < 1:
            dry_spell += 1
            longest_dry = max(longest_dry, dry_spell)
        else:
            dry_spell = 0
        if stage == "mid" and w.tmax >= k["t_abs"][1] - 2:
            heat_days += 1
        if w.tmin <= k["t_abs"][0] and (not hardy or stage in ("mid", "late")):
            cold_days += 1
        kill_streak = kill_streak + 1 if w.tmin <= kill_temp else 0

        stage_eta[stage] += eta
        stage_etc[stage] += etc
        irrigation_mm += irr
        rain_mm += w.rain
        canopy = _canopy(frac, bounds)
        daily.append({
            "day": i + 1,
            "date": w.date,
            "src": w.source,
            "stage": stage,
            "gdd": round(gdd),
            "progress": round(frac, 3),
            "canopy": round(canopy, 3),
            "tmax": round(w.tmax, 1),
            "tmin": round(w.tmin, 1),
            "rain": round(w.rain, 1),
            "irrigation": round(irr, 1),
            "et0": round(w.et0, 2),
            "etc": round(etc, 2),
            "water": round(1 - dr / max(taw, 1e-6), 3),
            "stress": round(1 - ks, 3),
            "drained": round(drained, 1),
        })
        if frac >= 1.0:
            matured_on = w.date
            break
        if kill_streak >= kill_needed and frac < 0.97:
            killed_on = w.date
            break

    # ---- yield ----
    yp = float(inp.yield_potential or k["yield_potential"])
    texture_factor = 1.0 if inp.texture in k["soils"] else 0.85
    water_factor = 1.0
    stage_water = {}
    for s in STAGES:
        ratio = stage_eta[s] / stage_etc[s] if stage_etc[s] > 0 else 1.0
        ky = k["ky"][KY_KEY[s]]
        f = max(0.0, 1 - ky * (1 - ratio))
        stage_water[s] = {"eta_etc": round(ratio, 3), "factor": round(f, 3)}
        water_factor *= f
    ph_factor = 0.6 + 0.4 * trapezoid(inp.ph, k["ph_abs"][0], k["ph_opt"][0], k["ph_opt"][1], k["ph_abs"][1])
    season_temp = sum(temp_samples) / len(temp_samples) if temp_samples else 25.0
    temp_factor = 0.5 + 0.5 * trapezoid(season_temp, k["t_abs"][0], k["t_opt"][0], k["t_opt"][1], k["t_abs"][1])
    heat_factor = max(0.6, 1 - 0.03 * heat_days)
    cold_factor = max(0.6, 1 - 0.02 * cold_days)
    n_applied = float(k["n_kg_ha"]) if inp.n_applied_kg_ha is None else float(inp.n_applied_kg_ha)
    n_supply = n_applied + inp.n_credit_kg_ha
    n_factor = min(1.0, 0.35 + 0.65 * n_supply / max(float(k["n_kg_ha"]), 1.0))
    maturity_factor = 1.0 if matured_on else max(0.3, frac ** 2)
    if killed_on:
        maturity_factor = 0.0 if frac < 0.6 else 0.35 * frac
    yield_t_ha = yp * texture_factor * water_factor * ph_factor * temp_factor * heat_factor * cold_factor * n_factor * maturity_factor

    price_t = float(inp.price_t or k["price_t"])
    cost_ha = float(inp.cost_ha or k["cost_ha"])
    irrigation_cost = irrigation_mm * inp.irrigation_cost_mm_ha
    revenue = yield_t_ha * price_t * inp.area_ha
    cost = (cost_ha + irrigation_cost) * inp.area_ha
    net = revenue - cost

    risks = _risks(k, inp, heat_days, cold_days, waterlog_days, longest_dry, matured_on, water_factor, n_factor, ph_factor, irrigation_mm)
    if killed_on:
        risks.insert(0, {"level": "high", "text": f"Killed by frost on {killed_on} (night below {kill_temp:.0f} C) before harvest. Sow so the crop matures before the first hard frost."})
    factors = {
        "water": round(water_factor, 3), "nutrients": round(n_factor, 3), "ph": round(ph_factor, 3),
        "temperature": round(temp_factor, 3), "heat": round(heat_factor, 3), "cold": round(cold_factor, 3),
        "texture": round(texture_factor, 3), "maturity": round(maturity_factor, 3),
    }
    suitability = round(100 * (water_factor * n_factor * ph_factor * temp_factor * heat_factor * cold_factor * texture_factor) ** (1 / 7), 1)
    return {
        "crop": k["id"],
        "label": k["label"],
        "sow_date": inp.sow_date.isoformat(),
        "matured_on": matured_on,
        "killed_on": killed_on,
        "days": len(daily),
        "area_ha": inp.area_ha,
        "irrigation": inp.irrigation,
        "texture": inp.texture,
        "suitability": suitability,
        "yield_t_ha": round(yield_t_ha, 2),
        "yield_potential_t_ha": yp,
        "yield_total_t": round(yield_t_ha * inp.area_ha, 2),
        "factors": factors,
        "stage_water": stage_water,
        "water": {"rain_mm": round(rain_mm), "irrigation_mm": round(irrigation_mm), "irrigation_events": sum(1 for d in daily if d["irrigation"] > 0)},
        "economics": {
            "currency": inp.currency, "price_t": round(price_t, 2), "cost_ha": round(cost_ha, 2), "irrigation_cost": round(irrigation_cost),
            "revenue": round(revenue), "cost": round(cost), "net": round(net),
            "roi_pct": round(100 * net / cost, 1) if cost else None,
        },
        "risks": risks,
        "sources": {s: sum(1 for d in daily if d["src"] == s) for s in ("observed", "forecast", "climatology")},
        "daily": daily,
        "tips": k["tips"],
    }


def _stage_bounds(sf: dict[str, float]) -> dict[str, float]:
    a = sf["ini"]; b = a + sf["dev"]; c = b + sf["mid"]
    return {"ini": a, "dev": b, "mid": c, "late": 1.0}


def _stage(frac: float, b: dict[str, float]) -> str:
    if frac < b["ini"]:
        return "ini"
    if frac < b["dev"]:
        return "dev"
    if frac < b["mid"]:
        return "mid"
    return "late"


def _kc(frac: float, b: dict[str, float], kc: dict[str, float]) -> float:
    if frac < b["ini"]:
        return kc["ini"]
    if frac < b["dev"]:
        t = (frac - b["ini"]) / max(b["dev"] - b["ini"], 1e-6)
        return kc["ini"] + t * (kc["mid"] - kc["ini"])
    if frac < b["mid"]:
        return kc["mid"]
    t = (frac - b["mid"]) / max(1.0 - b["mid"], 1e-6)
    return kc["mid"] + t * (kc["end"] - kc["mid"])


def _canopy(frac: float, b: dict[str, float]) -> float:
    """Visual canopy fraction 0..1 used by the twin: sigmoid rise, plateau, gentle senescence."""
    if frac < b["dev"]:
        t = frac / max(b["dev"], 1e-6)
        return 0.05 + 0.95 * (t * t * (3 - 2 * t))
    if frac < b["mid"]:
        return 1.0
    t = (frac - b["mid"]) / max(1.0 - b["mid"], 1e-6)
    return 1.0 - 0.35 * t


def _risks(k, inp, heat_days, cold_days, waterlog_days, longest_dry, matured_on, water_factor, n_factor, ph_factor, irrigation_mm) -> list[dict[str, str]]:
    out = []
    if not matured_on:
        out.append({"level": "high", "text": "The crop does not reach maturity in the simulated window; sow earlier or pick a shorter-duration crop."})
    if water_factor < 0.7:
        out.append({"level": "high", "text": f"Water stress cuts yield by about {round((1 - water_factor) * 100)}%. Irrigation at flowering would recover most of it."})
    elif water_factor < 0.9:
        out.append({"level": "medium", "text": "Mild water stress in one or more stages; one extra irrigation at flowering pays for itself."})
    if heat_days >= 3:
        out.append({"level": "high", "text": f"{heat_days} days above {k['t_abs'][1] - 2} C during flowering; expect sterility. Shift sowing by two weeks or choose a heat-tolerant variety."})
    if cold_days >= 3:
        out.append({"level": "medium" if cold_days < 15 else "high", "text": f"{cold_days} nights at or below {k['t_abs'][0]} C, this crop's growth floor; growth stalls and chilling damage is likely. Sow earlier or pick a cool-season crop."})
    if waterlog_days >= 2:
        out.append({"level": "medium", "text": "Heavy rain on heavy soil: waterlogging likely. Use ridges or raised beds and keep drains open."})
    if longest_dry >= 20 and inp.irrigation == "rainfed":
        out.append({"level": "medium", "text": f"A dry spell of {longest_dry} days falls inside the season; rain-fed cropping is exposed."})
    if n_factor < 0.85:
        out.append({"level": "medium", "text": f"Nitrogen supply covers only {round(n_factor * 100)}% of demand; add {max(0, round(k['n_kg_ha'] - inp.n_credit_kg_ha - (inp.n_applied_kg_ha or 0)))} kg/ha more nitrogen in splits."})
    if ph_factor < 0.85:
        out.append({"level": "medium", "text": f"Soil pH {inp.ph} is outside this crop's comfort range ({k['ph_opt'][0]}-{k['ph_opt'][1]}); amend or choose a tolerant crop."})
    if irrigation_mm > 600:
        out.append({"level": "low", "text": f"About {round(irrigation_mm)} mm of irrigation needed; check that the pump and water table can supply it."})
    if not out:
        out.append({"level": "low", "text": "No major agronomic risk flagged for this scenario."})
    return out
