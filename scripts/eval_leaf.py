"""Evaluate the trained leaf model on held-out validation images and on non-leaf images the model never saw.

    python scripts/eval_leaf.py

Reports: per-crop accuracy, confusion among the top offenders, and rejection rates of the scanner's gates on
(a) validation "other" images, (b) fresh synthetic junk, (c) leaf images (should NOT be rejected).
"""
from __future__ import annotations

import io
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from app.services import vision  # noqa: E402

DATA = ROOT / "data" / "leaf"


def jpeg(im: Image.Image) -> bytes:
    b = io.BytesIO(); im.convert("RGB").save(b, "JPEG", quality=85); return b.getvalue()


def main() -> None:
    random.seed(3)
    vision.warm()
    meta = json.loads((ROOT / "app" / "models" / "leaf_meta.json").read_text(encoding="utf-8"))
    print("model:", {k: meta[k] for k in ("arch", "size", "val_acc", "train_images", "val_images", "epochs")})
    print("ood:", meta["ood"])

    # per-crop accuracy from the per-class table
    by_crop: dict[str, list] = defaultdict(list)
    for cls, r in meta["per_class"].items():
        if "__" in cls and r["acc"] is not None:
            by_crop[cls.split("__")[0]].append((r["acc"], r["n"]))
    print("\nper-crop held-out accuracy (weighted):")
    for crop, rows in sorted(by_crop.items()):
        n = sum(x[1] for x in rows)
        acc = sum(x[0] * x[1] for x in rows) / n
        worst = min(((cls, r["acc"]) for cls, r in meta["per_class"].items() if cls.startswith(crop + "__")), key=lambda x: x[1])
        print(f"  {crop:<14} {acc*100:5.1f}%  n={n:<5} weakest: {worst[0].split('__')[1]} {worst[1]*100:.0f}%")

    # live gate test on samples from disk (a mix of classes; these overlap with training so treat as sanity only)
    def sample(cls, k):
        ps = list((DATA / cls).glob("*.jpg")); random.shuffle(ps); return ps[:k]
    leaf_classes = [c for c in meta["labels"] if c != "other"]
    leaf_samples = [(c, p) for c in random.sample(leaf_classes, 25) for p in sample(c, 4)]
    other_samples = [p for p in sample("other", 200)]
    verdicts = Counter(); correct = 0
    for c, p in leaf_samples:
        r = vision.predict(p.read_bytes())
        verdicts[r["verdict"]] += 1
        if r["top"] and r["top"]["id"] == c:
            correct += 1
    print(f"\nleaf samples ({len(leaf_samples)}): verdicts {dict(verdicts)}, top-1 correct {correct/len(leaf_samples)*100:.1f}%")
    v2 = Counter(vision.predict(p.read_bytes())["verdict"] for p in other_samples)
    print(f"stored non-leaf samples ({len(other_samples)}): verdicts {dict(v2)}")

    # fresh junk the model never saw: photos of nothing, drawings, screenshots-like, gradients with text
    fresh = []
    for i in range(120):
        w, h = random.randint(200, 900), random.randint(200, 900)
        im = Image.new("RGB", (w, h), tuple(random.randint(0, 255) for _ in range(3)))
        d = ImageDraw.Draw(im)
        for _ in range(random.randint(3, 30)):
            x, y = random.randint(0, w), random.randint(0, h)
            shape = random.choice(["rect", "ell", "line"])
            col = tuple(random.randint(0, 255) for _ in range(3))
            if shape == "rect": d.rectangle([x, y, x + random.randint(5, 200), y + random.randint(5, 200)], fill=col)
            elif shape == "ell": d.ellipse([x, y, x + random.randint(5, 200), y + random.randint(5, 200)], fill=col)
            else: d.line([x, y, random.randint(0, w), random.randint(0, h)], fill=col, width=random.randint(1, 12))
        fresh.append(jpeg(im))
    v3 = Counter(vision.predict(b)["verdict"] for b in fresh)
    print(f"fresh synthetic junk ({len(fresh)}): verdicts {dict(v3)}")
    rej = (v2["not_a_leaf"] + v2["uncertain"]) / len(other_samples)
    print(f"\nrejection of non-leaf photos: {rej*100:.1f}%  | false rejection of leaves: {(verdicts['not_a_leaf'])/len(leaf_samples)*100:.1f}%")


if __name__ == "__main__":
    main()
