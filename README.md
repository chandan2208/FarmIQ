# FarmIQ

A digital twin for one field, anywhere. FarmIQ reads the soil under a point from satellite maps, pulls the real
forecast and last year's weather, and simulates a whole cropping season day by day for any crop a farmer is
considering. The field is rendered in 3D and grows as you scrub the timeline. Around it: every regional crop ranked
at its best sowing window in local currency and units, a forecast turned into frost, workability and spray windows,
a leaf scanner with treatment protocols, live or reference prices, a multilingual advisor grounded in the plot, and a
small farmer circle.

Built for a farmer in Bihar, Iowa, Lincolnshire or Occitanie: the region decides currency, units, crop set, prices,
costs, attainable yields, sowing calendars and languages.

## What is real

| Feature | Data or model |
| --- | --- |
| Soil (pH, texture, organic carbon, nitrogen) | ISRIC SoilGrids 2.0, 250 m, 0-30 cm, worldwide |
| Region and place | Open-Meteo geocoding + BigDataCloud reverse geocoding (no keys) |
| Climate and observed weather | Open-Meteo archive (ERA5), last 365 days |
| Forecast, soil moisture, humidity | Open-Meteo, 16 days daily + hourly |
| Season simulator | FAO-56 root-zone water balance with crop coefficients, growing-degree-day phenology, FAO-33 stage-wise yield response, frost kill, stage-aware cold and heat stress, nutrient, pH and texture factors. 40 crops with curated parameters |
| Sowing-window finder | Every regional crop simulated at each candidate date allowed by the regional sowing calendar; best window and a risk-adjusted margin |
| Leaf scan | MobileNetV3-Small trained on 152,686 images from eight public sets (PlantVillage-derived, PlantDoc field photos, Paddy Doctor, two rice sets, sugarcane, Indian vegetables) covering 19 crops and 98 conditions, plus a 16k-image "not a leaf" class. 94.8% held-out accuracy on 17,791 images; non-leaf photos rejected by three gates (explicit "other" class, Mahalanobis distance in embedding space calibrated at 1.5% in-distribution rejection, softmax confidence). Training images are deleted after training; `scripts/fetch_hf_parquet.py`, `build_leaf_dataset.py`, `train_leaf.py`, `eval_leaf.py` rebuild it |
| Prices | India: Agmarknet daily mandi prices via data.gov.in, cached to disk. US, UK, EU, world: curated farm-gate reference prices (USDA NASS, AHDB, Eurostat, World Bank), shown in $/bu, £/t, €/t or ₹/quintal |
| Advisor | Gemini with structured plot context and the farmer's language when `GEMINI_API_KEY` is set; otherwise a rules engine (English) reading the same context |
| Interface | English, Hindi, Spanish, French, German, Italian; acres, hectares, bigha hint; °F or °C; inches or mm; bushels, tonnes or quintals |

## Run it

```bash
python -m venv venv && venv/Scripts/activate      # or source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                # optional keys
uvicorn app.main:app --reload --port 8790
```

Open http://127.0.0.1:8790. No build step: the frontend is plain ES modules with three.js from a pinned CDN.

Docker:

```bash
docker build -t farmiq . && docker run -p 8000:8000 --env-file .env farmiq
```

## Layout

```
app/
  main.py                FastAPI app, static mounts, SPA fallback
  config.py              settings from environment
  knowledge.py           crops, diseases, regions, units, economics per region
  services/              simulator, site (SoilGrids + archive + region), weather, market, vision, advisor, cache
  routers/               /api/site /api/weather /api/twin /api/market /api/scan /api/advisor /api/community
  data/                  crop_knowledge.json, crop_knowledge_global.json, disease_knowledge.json, regions.json
  models/                leaf_mobilenetv3.pt + leaf_meta.json
web/                     index.html, css/app.css, js/ (store, router, i18n, units, views, three/scene.js), PWA files
scripts/train_vision.py  fine-tune the leaf model from dataset/<class>/*.jpg
tests/                   pytest, offline
```

API docs at `/api/docs`.

## Adding a region or crop

- `app/data/regions.json`: currency, units preset, languages, crop list, `prices_t` (local currency per tonne),
  `costs_ha`, `yield_potential` (t/ha), and `sowing` (allowed months per crop). Countries map to regions by ISO code.
- `app/data/crop_knowledge*.json`: agronomic parameters per crop (FAO-56 Kc, FAO-33 Ky, GDD, temperature and
  rainfall envelopes, pH range, nutrient demand, tips).

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Retrain the leaf model

The full pipeline pulls public datasets from Hugging Face without any token, unifies them, trains, evaluates and
leaves only the 8 MB model behind:

```bash
for ds in ramyibrahim/plant-diseases-100k Project-AgML/plant_doc_classification anthony2261/paddy-disease-classification \
          Project-AgML/rice_leaf_disease_classification Project-AgML/rice_leaf_disease_classification_india \
          Project-AgML/sugarcane_leaf_disease_classification Project-AgML/plant_leaf_disease_classification \
          nelorth/oxford-flowers Bingsu/Cat_and_Dog; do python scripts/fetch_hf_parquet.py $ds; done
python scripts/fetch_hf_parquet.py ethz/food101 1          # one shard of food photos as negatives
python scripts/build_leaf_dataset.py 192                    # ~150k resized JPEGs under data/leaf/
python scripts/train_leaf.py 4 160 mobilenet_v3_small       # ~20 min/epoch on a 16-core CPU; checkpoints and resumes
python scripts/eval_leaf.py                                 # per-crop accuracy and rejection rates
rm -rf data/raw data/leaf
```

Weak spots in the current model are wheat (77% across 15 field conditions, tan spot 42%) and sugarcane smut (68%);
everything else is above 90% per crop. Add data for those classes and retrain to improve them.

## Environment

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | enables the language-model advisor |
| `DATA_GOV_API_KEY` | your own data.gov.in key for Agmarknet quotas |
| `ALLOWED_ORIGINS` | CORS, comma separated |
| `DATABASE_URL` | any SQLAlchemy URL; SQLite in `data/` by default |
| `FARMIQ_ENV` | `development` or `production` |
