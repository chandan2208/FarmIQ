"""
Unify every downloaded parquet source into one leaf-disease taxonomy and extract resized JPEGs.

    python scripts/build_leaf_dataset.py [max_side=192]

Reads data/raw/<owner__name>/*.parquet, maps each source label to a canonical "crop__condition" id,
writes data/leaf/<class>/<n>.jpg (longest side max_side px) and data/leaf/manifest.json.
Also generates synthetic non-leaf negatives for the "other" class.
"""
from __future__ import annotations

import io
import json
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "leaf"

# ---------- label maps ----------
RAMY_STATUS = {0: "tomato__leaf_mold", 1: "wheat__fusarium_head_blight", 2: "peach__bacterial_spot", 3: "corn__northern_leaf_blight", 4: "grape__esca", 5: "citrus__black_spot", 6: "wheat__healthy", 7: "wheat__black_rust", 8: "pepper__healthy", 9: "cherry__healthy", 10: "wheat__powdery_mildew", 11: "sugarcane__healthy", 12: "tomato__target_spot", 13: "cherry__powdery_mildew", 14: "rice__leaf_scald", 15: "cotton__bacterial_blight", 16: "rice__brown_spot", 17: "rice__bacterial_leaf_blight", 18: "tomato__healthy", 19: "wheat__aphid", 20: "wheat__common_root_rot", 21: "tomato__late_blight", 22: "apple__black_rot", 23: "tomato__bacterial_spot", 24: "apple__scab", 25: "wheat__mite", 26: "wheat__tan_spot", 27: "wheat__blast", 28: "potato__healthy", 29: "pepper__bacterial_spot", 30: "rice__sheath_blight", 31: "sugarcane__mosaic", 32: "grape__healthy", 33: "sugarcane__yellow_leaf", 34: "corn__healthy", 35: "tomato__septoria_leaf_spot", 36: "corn__common_rust", 37: "grape__black_rot", 38: "strawberry__leaf_scorch", 39: "wheat__brown_rust", 40: "corn__gray_leaf_spot", 41: "cotton__leaf_curl_virus", 42: "tomato__mosaic_virus", 43: "citrus__greening", 44: "apple__healthy", 45: "rice__healthy", 46: "wheat__leaf_blight", 47: "citrus__canker", 48: "wheat__septoria", 49: "grape__leaf_blight", 50: "cotton__healthy", 51: "peach__healthy", 52: "wheat__smut", 53: "cotton__fusarium_wilt", 54: "rice__blast", 55: "tomato__early_blight", 56: "potato__late_blight", 57: "wheat__yellow_rust", 58: "tomato__yellow_leaf_curl_virus", 59: "tomato__spider_mites", 60: "sugarcane__red_rot", 61: "wheat__stem_fly", 62: "sugarcane__rust", 63: "apple__cedar_apple_rust", 64: "citrus__healthy", 65: "potato__early_blight", 66: "strawberry__healthy"}
PLANTDOC = {0: "apple__scab", 1: "apple__healthy", 2: "apple__cedar_apple_rust", 3: "pepper__healthy", 4: "pepper__bacterial_spot", 5: None, 6: "cherry__healthy", 7: "corn__gray_leaf_spot", 8: "corn__northern_leaf_blight", 9: "corn__common_rust", 10: "peach__healthy", 11: "potato__early_blight", 12: "potato__late_blight", 13: None, 14: None, 15: None, 16: "strawberry__healthy", 17: "tomato__early_blight", 18: "tomato__septoria_leaf_spot", 19: "tomato__healthy", 20: "tomato__bacterial_spot", 21: "tomato__late_blight", 22: "tomato__mosaic_virus", 23: "tomato__yellow_leaf_curl_virus", 24: "tomato__leaf_mold", 25: "tomato__spider_mites", 26: "grape__healthy", 27: "grape__black_rot"}
PADDY = {0: "rice__bacterial_leaf_blight", 1: "rice__bacterial_leaf_streak", 2: "rice__bacterial_panicle_blight", 3: "rice__blast", 4: "rice__brown_spot", 5: "rice__dead_heart", 6: "rice__downy_mildew", 7: "rice__hispa", 8: "rice__healthy", 9: "rice__tungro"}
RICE6 = {0: "rice__bacterial_leaf_blight", 1: "rice__brown_spot", 2: "rice__healthy", 3: "rice__blast", 4: "rice__leaf_scald", 5: "rice__sheath_blight"}
RICE_IN = {0: "rice__bacterial_leaf_blight", 1: "rice__blast", 2: "rice__brown_spot", 3: "rice__tungro"}
SUGAR = {0: "sugarcane__banded_chlorosis", 1: "sugarcane__brown_spot", 2: "sugarcane__rust", 3: None, 4: "sugarcane__grassy_shoot", 5: "sugarcane__healthy", 6: "sugarcane__pokkah_boeng", 7: "sugarcane__sett_rot", 8: "sugarcane__smut", 9: "sugarcane__mosaic", 10: "sugarcane__yellow_leaf"}
AGML_PLANT = {0: "bitter_gourd", 1: "bottle_gourd", 2: "cauliflower", 3: "cucumber", 4: "brinjal", 5: "tomato"}
AGML_LABEL = {0: "anthracnose", 1: "anthracnose", 2: "black_rot", 3: "downy_mildew", 4: "downy_mildew", 5: "cercospora_leaf_spot", 6: "leaf_curl_virus", 7: "healthy", 8: "verticillium_wilt", 9: "healthy", 10: "fusarium_wilt", 11: "mosaic_virus", 12: "bacterial_spot", 13: "healthy", 14: "leaf_curl_virus", 15: "spotted_wilt"}

SOURCES = [
    ("ramyibrahim__plant-diseases-100k", "status", lambda r: RAMY_STATUS.get(r["status"])),
    ("Project-AgML__plant_doc_classification", "label", lambda r: PLANTDOC.get(r["label"])),
    ("anthony2261__paddy-disease-classification", "label", lambda r: PADDY.get(r["label"])),
    ("Project-AgML__rice_leaf_disease_classification", "label", lambda r: RICE6.get(r["label"])),
    ("Project-AgML__rice_leaf_disease_classification_india", "label", lambda r: RICE_IN.get(r["label"])),
    ("Project-AgML__sugarcane_leaf_disease_classification", "label", lambda r: SUGAR.get(r["label"])),
    ("Project-AgML__plant_leaf_disease_classification", "label", lambda r: f"{AGML_PLANT[r['plant_type']]}__{AGML_LABEL[r['label']]}"),
    ("nelorth__oxford-flowers", "label", lambda r: "other"),
    ("Bingsu__Cat_and_Dog", "labels", lambda r: "other"),
    ("ethz__food101", "label", lambda r: "other"),
]
NEG_CAP = {"nelorth__oxford-flowers": 5000, "Bingsu__Cat_and_Dog": 4000, "ethz__food101": 6000}
MIN_CLASS = 60


def resize_bytes(b: bytes, max_side: int) -> bytes | None:
    try:
        im = Image.open(io.BytesIO(b))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side), Image.BILINEAR)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=88)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def process_shard(args):
    path, label_col, src_name, max_side, cap = args
    f = pq.ParquetFile(path)
    cols = ["image", label_col] + (["plant_type"] if "plant_type" in f.schema_arrow.names else [])
    written: Counter = Counter()
    n = 0
    mapper = dict((s[0], s[2]) for s in SOURCES)[src_name]
    for batch in f.iter_batches(batch_size=256, columns=cols):
        rows = batch.to_pylist()
        for r in rows:
            if cap is not None and n >= cap:
                return dict(written)
            cid = mapper(r)
            if cid is None:
                continue
            b = r["image"]["bytes"] if isinstance(r["image"], dict) else r["image"]
            data = resize_bytes(b, max_side)
            if not data:
                continue
            d = OUT / cid
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{src_name[:12]}_{Path(path).stem[-6:]}_{n:06d}.jpg").write_bytes(data)
            written[cid] += 1
            n += 1
    return dict(written)


def synthetic_negatives(n: int, max_side: int) -> int:
    """Noise, gradients, flat colours, text-like blocks and blurred shapes: the junk people actually upload."""
    d = OUT / "other"
    d.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(11)
    for i in range(n):
        w, h = rnd.randint(120, max_side), rnd.randint(120, max_side)
        kind = i % 5
        if kind == 0:
            im = Image.effect_noise((w, h), rnd.randint(20, 90)).convert("RGB")
        elif kind == 1:
            im = Image.new("RGB", (w, h), tuple(rnd.randint(0, 255) for _ in range(3)))
        elif kind == 2:
            im = Image.linear_gradient("L").resize((w, h)).convert("RGB")
            im = ImageOps.colorize(im.convert("L"), tuple(rnd.randint(0, 255) for _ in range(3)), tuple(rnd.randint(0, 255) for _ in range(3)))
        elif kind == 3:
            im = Image.new("RGB", (w, h), (rnd.randint(200, 255),) * 3)
            dr = ImageDraw.Draw(im)
            for _ in range(rnd.randint(5, 25)):
                x, y = rnd.randint(0, w), rnd.randint(0, h)
                dr.rectangle([x, y, x + rnd.randint(10, 80), y + rnd.randint(2, 8)], fill=(rnd.randint(0, 80),) * 3)
        else:
            im = Image.new("RGB", (w, h), tuple(rnd.randint(0, 255) for _ in range(3)))
            dr = ImageDraw.Draw(im)
            for _ in range(rnd.randint(2, 8)):
                x, y = rnd.randint(0, w), rnd.randint(0, h)
                dr.ellipse([x, y, x + rnd.randint(10, 90), y + rnd.randint(10, 90)], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
            im = im.filter(ImageFilter.GaussianBlur(rnd.randint(0, 4)))
        im.save(d / f"synthetic_{i:05d}.jpg", "JPEG", quality=85)
    return n


def main() -> None:
    max_side = int(sys.argv[1]) if len(sys.argv) > 1 else 192
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for src_name, label_col, _ in SOURCES:
        d = RAW / src_name
        if not d.exists():
            print("missing", src_name, flush=True)
            continue
        shards = sorted(d.glob("*.parquet"))
        cap = NEG_CAP.get(src_name)
        per_shard_cap = None if cap is None else max(1, cap // max(1, len(shards)))
        for p in shards:
            jobs.append((str(p), label_col, src_name, max_side, per_shard_cap))
    print(f"{len(jobs)} shards", flush=True)
    totals: Counter = Counter()
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(process_shard, jobs)):
            totals.update(res)
            print(f"  shard {i + 1}/{len(jobs)}: {sum(res.values())} images", flush=True)
    totals["other"] += synthetic_negatives(2500, max_side)
    # drop tiny classes
    dropped = []
    for cid, n in list(totals.items()):
        if n < MIN_CLASS:
            dropped.append((cid, n))
            for p in (OUT / cid).glob("*.jpg"):
                p.unlink()
            (OUT / cid).rmdir()
            del totals[cid]
    manifest = {"classes": dict(sorted(totals.items())), "dropped": dropped, "max_side": max_side, "sources": [s[0] for s in SOURCES]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest["classes"], indent=1))
    print("total", sum(totals.values()), "classes", len(totals), "dropped", dropped)


if __name__ == "__main__":
    main()
