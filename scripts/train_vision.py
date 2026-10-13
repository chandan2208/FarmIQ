"""
Fine-tune a pretrained MobileNetV3-Small on the PlantVillage-style folder dataset.

    python scripts/train_vision.py [images_per_class] [epochs] [image_size]

Expects dataset/<class_name>/*.jpg. Writes app/models/leaf_mobilenetv3.pt and app/models/leaf_meta.json
(architecture, image size, normalisation, labels and validation accuracy) which app/services/vision.py
loads in preference to the legacy CNN. CPU-friendly: 400 images/class at 160 px trains in minutes.
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, models, transforms

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "dataset"
OUT = ROOT / "app" / "models"
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


def main() -> None:
    per_class = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 160
    random.seed(7); torch.manual_seed(7)
    if not DATA.exists():
        sys.exit(f"dataset folder not found at {DATA}")

    tf_train = transforms.Compose([
        transforms.RandomResizedCrop(size, scale=(0.65, 1.0)), transforms.RandomHorizontalFlip(), transforms.RandomVerticalFlip(),
        transforms.ColorJitter(0.25, 0.25, 0.2, 0.03), transforms.ToTensor(), transforms.Normalize(MEAN, STD),
    ])
    tf_val = transforms.Compose([transforms.Resize((size, size)), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])

    base = datasets.ImageFolder(DATA)
    by_class: dict[int, list[int]] = defaultdict(list)
    for i, (_, t) in enumerate(base.samples):
        by_class[t].append(i)
    train_idx, val_idx = [], []
    for t, idxs in by_class.items():
        random.shuffle(idxs)
        sel = idxs[:per_class]
        n_val = max(20, int(0.15 * len(sel)))
        val_idx += sel[:n_val]
        train_idx += sel[n_val:]
    train_ds = Subset(datasets.ImageFolder(DATA, transform=tf_train), train_idx)
    val_ds = Subset(datasets.ImageFolder(DATA, transform=tf_val), val_idx)
    train_dl = DataLoader(train_ds, batch_size=48, shuffle=True, num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=96, shuffle=False, num_workers=0)
    labels = base.classes
    print(f"classes={len(labels)} train={len(train_idx)} val={len(val_idx)} size={size} epochs={epochs}", flush=True)

    model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(labels))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, total_steps=epochs * len(train_dl))
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.05)

    best = 0.0
    for epoch in range(epochs):
        model.train(); t0 = time.time(); running = 0.0
        for step, (x, y) in enumerate(train_dl):
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward(); opt.step(); sched.step()
            running += loss.item()
            if (step + 1) % 20 == 0:
                print(f"  epoch {epoch + 1} step {step + 1}/{len(train_dl)} loss {running / (step + 1):.3f}", flush=True)
        acc = evaluate(model, val_dl, device)
        print(f"epoch {epoch + 1}: loss {running / len(train_dl):.3f} val_acc {acc:.3f} ({time.time() - t0:.0f}s)", flush=True)
        if acc >= best:
            best = acc
            OUT.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), OUT / "leaf_mobilenetv3.pt")
            (OUT / "leaf_meta.json").write_text(json.dumps({
                "arch": "mobilenet_v3_small", "size": size, "mean": MEAN, "std": STD, "labels": labels,
                "val_acc": round(best, 4), "train_images": len(train_idx), "val_images": len(val_idx), "epochs": epoch + 1,
            }, indent=1), encoding="utf-8")
    print(f"done. best val_acc={best:.3f} -> {OUT / 'leaf_mobilenetv3.pt'}", flush=True)


@torch.no_grad()
def evaluate(model, dl, device) -> float:
    model.eval(); correct = total = 0
    for x, y in dl:
        pred = model(x.to(device)).argmax(1).cpu()
        correct += (pred == y).sum().item(); total += y.numel()
    return correct / max(total, 1)


if __name__ == "__main__":
    main()
