"""Region engine: units, currency, prices and calendars. Offline."""
from __future__ import annotations

from datetime import date, timedelta

from app.knowledge import BUSHEL_KG, crops, economics_for, region_for, regions, season_label
from app.services.market import reference
from app.services.simulator import Day, SimInput, simulate


def test_country_maps_to_region_and_units():
    assert region_for("IN")["id"] == "IN" and region_for("IN")["unit_preset"]["area"] == "acre"
    assert region_for("US")["currency"] == "USD" and region_for("US")["unit_preset"]["temp"] == "F"
    assert region_for("GB")["id"] == "UK" and region_for("GB")["currency"] == "GBP"
    assert region_for("FR")["id"] == "EU" and region_for("DE")["currency"] == "EUR"
    assert region_for("BR")["id"] == "WORLD" and region_for(None)["id"] == "WORLD"


def test_every_regional_crop_exists_with_price_cost_yield():
    for rid, r in regions().items():
        for cid in r["crops"]:
            assert cid in crops(), (rid, cid)
            eco = economics_for(cid, r)
            assert eco["price_t"] > 0 and eco["cost_ha"] > 0 and eco["yield_potential"] > 0, (rid, cid)
            assert eco["currency"] == r["currency"]
        for cid, months in r.get("sowing", {}).items():
            assert cid in crops() and all(1 <= m <= 12 for m in months), (rid, cid)


def test_reference_prices_in_local_trade_units():
    us = reference("US")
    maize = next(r for r in us["rows"] if r["crop"] == "maize")
    assert maize["local_unit"] == "bu" and abs(maize["local_price"] - maize["price_t"] * BUSHEL_KG["maize"] / 1000) < 0.01
    india = reference("IN")
    rice = next(r for r in india["rows"] if r["crop"] == "rice")
    assert rice["local_unit"] == "quintal" and rice["local_price"] == rice["price_t"] / 10
    uk = reference("UK")
    assert all(r["local_unit"] == "t" for r in uk["rows"]) and uk["region"]["currency"] == "GBP"


def test_season_labels_follow_region_and_hemisphere():
    assert season_label(date(2026, 7, 1), region_for("IN"), 26.0) == "kharif"
    assert season_label(date(2026, 11, 1), region_for("IN"), 26.0) == "rabi"
    assert season_label(date(2026, 10, 1), region_for("GB"), 53.0) == "autumn"
    assert season_label(date(2026, 4, 1), region_for("BR"), -20.0) == "autumn"


def synthetic(sow: date, n: int, tmax: float, tmin: float) -> list[Day]:
    return [Day((sow + timedelta(days=i)).isoformat(), tmax, tmin, 4.0 if i % 4 == 0 else 0.0, 3.0, "test") for i in range(n)]


def test_frost_kills_tender_crop_but_not_winter_cereal():
    sow = date(2026, 10, 1)
    cold = synthetic(sow, 60, 12, 6) + synthetic(sow + timedelta(days=60), 100, 2, -6)
    tomato = simulate(SimInput(crop="tomato", sow_date=sow, weather=cold))
    wheat = simulate(SimInput(crop="wheat", sow_date=sow, weather=cold + synthetic(sow + timedelta(days=160), 150, 22, 10)))
    assert tomato["killed_on"] is not None and tomato["yield_t_ha"] == 0
    assert wheat["killed_on"] is None and wheat["matured_on"] is not None and wheat["yield_t_ha"] > 3


def test_regional_economics_change_currency_and_margin():
    sow = date(2026, 5, 1)
    wx = synthetic(sow, 160, 28, 16)
    us = region_for("US")
    eco = economics_for("maize", us)
    r = simulate(SimInput(crop="maize", sow_date=sow, price_t=eco["price_t"], cost_ha=eco["cost_ha"], yield_potential=eco["yield_potential"], currency="USD", irrigation="full", weather=wx))
    assert r["economics"]["currency"] == "USD"
    assert r["yield_potential_t_ha"] == eco["yield_potential"]
    assert abs(r["economics"]["revenue"] - r["yield_t_ha"] * eco["price_t"]) < 2
