"""Engine tests: run offline with synthetic weather so they never touch the network."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.knowledge import SOIL_WATER, crops, diseases, trapezoid
from app.services.simulator import Day, SimInput, build_series, simulate


def synthetic(sow: date, n: int, *, tmax=32.0, tmin=22.0, rain_every=5, rain_mm=18.0, et0=4.5) -> list[Day]:
    return [Day((sow + timedelta(days=i)).isoformat(), tmax, tmin, rain_mm if i % rain_every == 0 else 0.0, et0, "test") for i in range(n)]


def test_knowledge_base_is_consistent():
    for cid, k in crops().items():
        assert k["t_abs"][0] < k["t_opt"][0] <= k["t_opt"][1] < k["t_abs"][1], cid
        assert k["rain_abs"][0] <= k["rain_opt"][0] <= k["rain_opt"][1] <= k["rain_abs"][1], cid
        assert abs(sum(k["stage_frac"].values()) - 1.0) < 1e-6, cid
        assert set(k["kc"]) == {"ini", "mid", "end"}, cid
        assert k["yield_potential"] > 0 and k["price_q"] > 0 and k["cost_ha"] > 0, cid
        assert set(k["tips"]) == {"sowing", "irrigation", "fertilizer", "pests", "harvest"}, cid
    for did, d in diseases().items():
        assert d["severity"] in {"none", "medium", "high", "critical"}, did
        assert d["act_now"], did
    assert set(SOIL_WATER) >= {"loamy", "clay", "sandy"}


def test_trapezoid_membership():
    assert trapezoid(25, 10, 20, 30, 40) == 1.0
    assert trapezoid(15, 10, 20, 30, 40) == pytest.approx(0.5)
    assert trapezoid(5, 10, 20, 30, 40) == 0.0
    assert trapezoid(45, 10, 20, 30, 40) == 0.0


def test_rice_matures_and_yields_near_potential_with_good_water():
    sow = date(2026, 6, 20)
    r = simulate(SimInput(crop="rice", sow_date=sow, texture="clay", ph=6.5, n_credit_kg_ha=50, irrigation="full", weather=synthetic(sow, 200)))
    assert r["matured_on"] is not None
    assert 100 <= r["days"] <= 160
    assert r["yield_t_ha"] > 0.85 * r["yield_potential_t_ha"]
    assert r["economics"]["net"] > 0
    assert r["daily"][-1]["progress"] == 1.0
    assert r["daily"][0]["stage"] == "ini" and r["daily"][-1]["stage"] == "late"


def test_rainfed_dry_season_stresses_and_cuts_yield():
    sow = date(2026, 6, 20)
    wet = simulate(SimInput(crop="maize", sow_date=sow, irrigation="full", weather=synthetic(sow, 160)))
    dry = simulate(SimInput(crop="maize", sow_date=sow, irrigation="rainfed", weather=synthetic(sow, 160, rain_every=1000, rain_mm=0.0, et0=6.0)))
    assert dry["yield_t_ha"] < 0.6 * wet["yield_t_ha"]
    assert dry["factors"]["water"] < wet["factors"]["water"]
    assert any(d["stress"] > 0.3 for d in dry["daily"])
    assert any(r["level"] == "high" for r in dry["risks"])
    assert dry["water"]["irrigation_mm"] == 0 and wet["water"]["irrigation_mm"] > 0


def test_cold_season_does_not_mature_warm_crop():
    sow = date(2026, 11, 1)
    r = simulate(SimInput(crop="cotton", sow_date=sow, weather=synthetic(sow, 120, tmax=18, tmin=6)))
    assert r["matured_on"] is None
    assert r["factors"]["maturity"] < 1.0
    assert any("maturity" in x["text"] for x in r["risks"])


def test_ph_and_nitrogen_factors_move_yield():
    sow = date(2026, 11, 1)
    base = SimInput(crop="wheat", sow_date=sow, ph=7.0, n_credit_kg_ha=40, irrigation="full", weather=synthetic(sow, 170, tmax=24, tmin=10, et0=3.0))
    good = simulate(base)
    acidic = simulate(SimInput(**{**base.__dict__, "ph": 4.9}))
    starved = simulate(SimInput(**{**base.__dict__, "n_applied_kg_ha": 0, "n_credit_kg_ha": 10}))
    assert acidic["factors"]["ph"] < good["factors"]["ph"]
    assert starved["factors"]["nutrients"] < good["factors"]["nutrients"]
    assert starved["yield_t_ha"] < good["yield_t_ha"]


def test_build_series_prefers_forecast_then_observed_then_climatology():
    sow = date(2026, 9, 20)
    forecast = [{"date": (sow + timedelta(days=i)).isoformat(), "tmax": 30, "tmin": 20, "rain": 1, "et0": 3} for i in range(5, 10)]
    archive = [{"date": (sow + timedelta(days=i)).isoformat(), "tmax": 31, "tmin": 21, "rain": 2, "et0": 3} for i in range(0, 5)]
    archive += [{"date": (sow + timedelta(days=i - 365)).isoformat(), "tmax": 28, "tmin": 18, "rain": 0, "et0": 3} for i in range(0, 40)]
    series = build_series(sow, 20, forecast, archive)
    assert [d.source for d in series[:12]] == ["observed"] * 5 + ["forecast"] * 5 + ["climatology"] * 2
    assert series[15].tmax == pytest.approx(28)
