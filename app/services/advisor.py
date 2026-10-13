"""Grounded agronomy advisor. Uses Gemini when a key is configured, otherwise a deterministic rules engine.

Every answer is grounded in the caller's twin state (site, forecast, simulation), which is passed as
structured context, so the model talks about *this* plot rather than farming in general.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from app.config import settings
from app.knowledge import crops

log = logging.getLogger("farmiq.advisor")

SYSTEM = """You are FarmIQ's agronomist. You advise Indian smallholder farmers about one specific plot.
You are given CONTEXT as JSON: the plot's soil, climate, 16-day forecast, disease pressure, the current
season simulation (crop, stage, yield forecast, risks) and mandi prices when available.
Rules:
- Ground every claim in the context; quote the numbers you use (dates, mm of rain, kg/ha, prices).
- Give actions a farmer can take this week, in order of urgency. Name products with doses when relevant.
- If the context lacks what you need, say what to measure or upload instead of guessing.
- Plain, direct sentences. No emojis, no headings, no bullet symbols other than '-'. Under 180 words unless asked for detail.
- Never invent prices or forecasts that are not in the context."""


LANGUAGES = {"en": "English", "hi": "Hindi (Devanagari)", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese", "pl": "Polish"}


async def stream(question: str, context: dict[str, Any], history: list[dict[str, str]], language: str = "en") -> AsyncIterator[str]:
    if settings.gemini_api_key:
        try:
            async for chunk in _gemini(question, context, history, language):
                yield chunk
            return
        except Exception as exc:  # noqa: BLE001 - degrade to rules, never fail the farmer
            log.warning("gemini failed, using rules engine: %s", exc)
            yield "\n"
    async for chunk in _rules(question, context):
        yield chunk


async def _gemini(question: str, context: dict[str, Any], history: list[dict[str, str]], language: str = "en") -> AsyncIterator[str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    contents: list[types.Content] = []
    for turn in history[-8:]:
        role = "user" if turn.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=turn.get("text", ""))]))
    region = (context.get("site") or {}).get("region") or {}
    units = region.get("unit_preset") or {}
    locale_note = (
        f"The farmer is in {region.get('name', 'an unknown region')}. Use {region.get('currency', 'local currency')} for money, "
        f"{units.get('area', 'ha')} for area, {units.get('yield', 't/ha')} for yield, degrees {units.get('temp', 'C')} and {units.get('rain', 'mm')} for rain. "
        f"Answer in {LANGUAGES.get(language, 'English')}."
    )
    prompt = f"{locale_note}\n\nCONTEXT:\n{json.dumps(context, ensure_ascii=False)[:14000]}\n\nQUESTION: {question}"
    contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
    loop = asyncio.get_running_loop()

    def run():
        return client.models.generate_content_stream(
            model=settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.4, max_output_tokens=700),
        )

    stream_obj = await loop.run_in_executor(None, run)
    iterator = iter(stream_obj)
    while True:
        chunk = await loop.run_in_executor(None, next, iterator, None)
        if chunk is None:
            break
        if chunk.text:
            yield chunk.text


async def _rules(question: str, ctx: dict[str, Any]) -> AsyncIterator[str]:
    """Deterministic advisor: reads the same context and answers the common questions well."""
    q = question.lower()
    sim = ctx.get("simulation") or {}
    fc = ctx.get("forecast") or {}
    soil = (ctx.get("site") or {}).get("soil") or {}
    days = fc.get("days") or []
    lines: list[str] = []

    rain_week = round(sum(d.get("rain", 0) for d in days[:7]))
    hot = [d for d in days[:7] if (d.get("tmax") or 0) >= 38]
    pressure = (fc.get("disease_pressure") or [])[:2]

    if any(w in q for w in ("irrigat", "water", "paani", "pani")):
        if sim:
            stress_days = [d for d in sim.get("daily", []) if d.get("src") == "forecast" and d.get("stress", 0) > 0.2]
            if stress_days:
                lines.append(f"Irrigate on {stress_days[0]['date']}: the root zone drops below the safe level then and {sim['label']} is in its {sim['daily'][-1]['stage']} stage.")
            else:
                lines.append(f"No irrigation needed in the next 16 days; the forecast gives {rain_week} mm this week and the root zone stays above the stress line.")
            lines.append(f"Whole-season estimate: {sim['water']['irrigation_mm']} mm over {sim['water']['irrigation_events']} events with the '{sim['irrigation']}' strategy.")
        else:
            lines.append(f"This week brings about {rain_week} mm of rain. Run a season simulation in the Twin so I can time irrigations to the crop stage.")
    elif any(w in q for w in ("spray", "fungicide", "pesticide", "disease", "blight", "pest")):
        if pressure:
            top = pressure[0]
            lines.append(f"Highest disease pressure this week: {top['name']} on {top['crop']} at {top['pressure']}/100.")
        windows = [(d["date"], d.get("spray_windows", [])) for d in days[:4]]
        good = [(dt, w[0]) for dt, w in windows if w]
        if good:
            dt, w = good[0]
            lines.append(f"Best spray window: {dt} from {w['start']} to {w['end']} (light wind, no rain within six hours).")
        else:
            lines.append("No clean spray window in the next four days; wind or rain would waste the application.")
        lines.append("Upload a leaf photo in Scan to get a specific product and dose.")
    elif any(w in q for w in ("sow", "plant", "when", "bo", "kab")):
        if sim:
            lines.append(f"With sowing on {sim['sow_date']}, {sim['label']} reaches maturity on {sim.get('matured_on') or 'a date beyond the window'} with a forecast of {sim['yield_t_ha']} t/ha.")
        if hot:
            lines.append(f"{len(hot)} days above 38 C this week; delay transplanting of tender seedlings until after {hot[-1]['date']}.")
        elif rain_week >= 30:
            lines.append(f"About {rain_week} mm of rain this week: good moisture for sowing kharif crops right after the first heavy shower.")
        else:
            lines.append("The week is dry; pre-irrigate the seedbed before sowing.")
    elif any(w in q for w in ("price", "sell", "mandi", "market", "bhav")):
        market = ctx.get("market") or {}
        rows = market.get("summary") or []
        if rows:
            for r in rows[:3]:
                sig = r.get("signal")
                extra = f", {sig['delta_pct']:+.0f}% against the reference price" if sig else ""
                lines.append(f"{r['commodity']}: median {r['median_modal']} per quintal across {r['markets']} markets, best at {r['best_market']}{extra}.")
        else:
            lines.append("Open the Mandi page and pick your state to load today's prices, then ask me again.")
    elif any(w in q for w in ("fertil", "urea", "npk", "nitrogen", "khad")):
        crop_id = sim.get("crop")
        if crop_id and crop_id in crops():
            k = crops()[crop_id]
            credit = soil.get("n_credit_kg_ha", 0)
            need = max(0, round(k["n_kg_ha"] - credit))
            lines.append(f"{k['label']} wants about {k['n_kg_ha']} kg/ha nitrogen; your soil mineralises roughly {credit} kg/ha, so apply around {need} kg/ha ({round(need / 0.46)} kg urea) in splits.")
            lines.append(k["tips"]["fertilizer"])
        else:
            lines.append(f"Soil organic carbon is {soil.get('organic_carbon_gkg', '?')} g/kg and pH {soil.get('ph', '?')}. Pick a crop in the Twin and I will size the dose.")
    else:
        if sim:
            risk = sim.get("risks", [{}])[0].get("text", "")
            lines.append(f"{sim['label']} on this plot: {sim['yield_t_ha']} t/ha expected, net {sim['economics'].get('currency', '')} {sim['economics']['net']:,} on {sim['area_ha']} ha. Main risk: {risk}")
        if days:
            lines.append(f"Next 7 days: {rain_week} mm rain, highs up to {max(d['tmax'] for d in days[:7])} C.")
        if pressure:
            lines.append(f"Watch for {pressure[0]['name']} ({pressure[0]['pressure']}/100 pressure).")
        if not lines:
            lines.append("Set your plot location first; then I can talk about your soil, forecast, crop plan and prices.")

    text = " ".join(lines)
    for i in range(0, len(text), 24):
        yield text[i:i + 24]
        await asyncio.sleep(0.012)


def mode() -> str:
    return "gemini" if settings.gemini_api_key else "rules"
