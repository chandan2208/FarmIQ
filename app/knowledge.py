"""Curated agronomic knowledge: crop parameters, disease protocols, regional economics and units."""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Any

from app.config import settings

# Soil water constants per texture class: (field capacity, wilting point) as volumetric fractions.
SOIL_WATER = {
    "sandy": (0.12, 0.05),
    "sandyloam": (0.20, 0.09),
    "loamy": (0.27, 0.12),
    "alluvial": (0.26, 0.12),
    "red": (0.22, 0.10),
    "laterite": (0.20, 0.10),
    "clay": (0.36, 0.21),
    "black": (0.38, 0.22),
}
SOIL_LABELS = {
    "sandy": "Sandy", "sandyloam": "Sandy loam", "loamy": "Loam", "alluvial": "Alluvial",
    "red": "Red soil", "laterite": "Laterite", "clay": "Clay", "black": "Black cotton soil",
}

# Kilograms per bushel for US-style yield and price display.
BUSHEL_KG = {"maize": 25.4, "wheat": 27.2, "soybean": 27.2, "jowar": 25.4, "oats": 14.5, "barley": 21.8, "rye": 25.4, "canola": 22.7, "dry_beans": 27.2, "chickpea": 27.2, "lentil": 27.2, "pea": 27.2, "sunflower": 12.7}

UNIT_PRESETS = {
    "metric": {"area": "ha", "yield": "t/ha", "temp": "C", "rain": "mm", "price": "t"},
    "uk": {"area": "ha", "yield": "t/ha", "temp": "C", "rain": "mm", "price": "t"},
    "india": {"area": "acre", "yield": "q/acre", "temp": "C", "rain": "mm", "price": "quintal"},
    "us": {"area": "acre", "yield": "bu/acre", "temp": "F", "rain": "in", "price": "bu"},
}


@lru_cache(maxsize=1)
def crops() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in ("crop_knowledge.json", "crop_knowledge_global.json"):
        raw = json.loads((settings.data_dir / name).read_text(encoding="utf-8"))
        raw.pop("_doc", None)
        out.update(raw)
    for key, value in out.items():
        value["id"] = key
        value["price_t"] = float(value["price_q"]) * 10  # INR per tonne, the India baseline
        value["bu_kg"] = BUSHEL_KG.get(key)
    return out


@lru_cache(maxsize=1)
def diseases() -> dict[str, dict[str, Any]]:
    return json.loads((settings.data_dir / "disease_knowledge.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _regions_raw() -> dict[str, Any]:
    return json.loads((settings.data_dir / "regions.json").read_text(encoding="utf-8"))


def region_for(country_code: str | None) -> dict[str, Any]:
    raw = _regions_raw()
    rid = raw["countries"].get((country_code or "").upper(), "WORLD")
    r = dict(raw["regions"][rid])
    r["id"] = rid
    r["country_code"] = (country_code or "").upper() or None
    r["unit_preset"] = UNIT_PRESETS[r["units"]]
    return r


def regions() -> dict[str, dict[str, Any]]:
    return {rid: region_for_id(rid) for rid in _regions_raw()["regions"]}


def region_for_id(rid: str) -> dict[str, Any]:
    raw = _regions_raw()
    r = dict(raw["regions"].get(rid, raw["regions"]["WORLD"]))
    r["id"] = rid if rid in raw["regions"] else "WORLD"
    r["unit_preset"] = UNIT_PRESETS[r["units"]]
    return r


def crop(crop_id: str) -> dict[str, Any]:
    data = crops()
    key = crop_id.strip().lower()
    if key not in data:
        raise KeyError(f"unknown crop '{crop_id}'")
    return data[key]


def economics_for(crop_id: str, region: dict[str, Any]) -> dict[str, float | str]:
    """Price per tonne, cost per hectare and attainable yield for a crop in a region, with the India baseline as fallback."""
    k = crop(crop_id)
    if region["id"] == "IN":
        return {"price_t": k["price_t"], "cost_ha": float(k["cost_ha"]), "yield_potential": float(k["yield_potential"]), "currency": "INR", "source": "region"}
    prices = region.get("prices_t", {})
    costs = region.get("costs_ha", {})
    yp = region.get("yield_potential", {})
    if crop_id in prices:
        return {"price_t": float(prices[crop_id]), "cost_ha": float(costs.get(crop_id, k["cost_ha"] / 80)), "yield_potential": float(yp.get(crop_id, k["yield_potential"])), "currency": region["currency"], "source": "region"}
    # Not a regional crop: convert the India baseline at a rough purchasing-power rate so the number is at least in the right currency.
    fx = {"USD": 1 / 84.0, "GBP": 1 / 106.0, "EUR": 1 / 91.0}.get(region["currency"], 1.0)
    return {"price_t": round(k["price_t"] * fx, 2), "cost_ha": round(k["cost_ha"] * fx, 2), "yield_potential": float(k["yield_potential"]), "currency": region["currency"], "source": "converted"}


def texture_from_fractions(sand_pct: float, clay_pct: float) -> str:
    if clay_pct >= 40:
        return "clay"
    if sand_pct >= 70:
        return "sandy"
    if sand_pct >= 52 and clay_pct < 20:
        return "sandyloam"
    return "loamy"


def trapezoid(x: float, abs_lo: float, opt_lo: float, opt_hi: float, abs_hi: float) -> float:
    """Ecocrop-style membership: 0 outside absolute range, 1 inside optimum, linear between."""
    if x <= abs_lo or x >= abs_hi:
        return 0.0
    if opt_lo <= x <= opt_hi:
        return 1.0
    if x < opt_lo:
        return (x - abs_lo) / max(opt_lo - abs_lo, 1e-6)
    return (abs_hi - x) / max(abs_hi - opt_hi, 1e-6)


def season_label(sow: date, region: dict[str, Any], lat: float) -> str:
    """Name the sowing season the way farmers in that region say it."""
    m = sow.month
    if region.get("id") != "WORLD":
        for name, months in region.get("seasons", {}).items():
            if m in months:
                return name
    north = lat >= 0
    if m in (3, 4, 5):
        return "spring" if north else "autumn"
    if m in (6, 7, 8):
        return "summer" if north else "winter"
    if m in (9, 10, 11):
        return "autumn" if north else "spring"
    return "winter" if north else "summer"
