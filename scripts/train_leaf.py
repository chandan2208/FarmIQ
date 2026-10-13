"""
Train the leaf classifier on data/leaf/<class>/*.jpg with an explicit "other" class and open-set statistics.

    python scripts/train_leaf.py [epochs=4] [size=160] [arch=mobilenet_v3_small|mobilenet_v3_large]

Writes app/models/leaf_mobilenetv3.pt and app/models/leaf_meta.json (labels, normalisation, accuracy per class,
class-mean embeddings + shared precision matrix for Mahalanobis rejection, calibrated thresholds).
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "leaf"
OUT = ROOT / "app" / "models"
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


class Leaves(Dataset):
    def __init__(self, items, tf):
        self.items, self.tf = items, tf

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p, y = self.items[i]
        try:
            im = Image.open(p).convert("RGB")
        except Exception:  # noqa: BLE001
            im = Image.new("RGB", (64, 64))
        return self.tf(im), y


def build_model(arch: str, n: int):
    if arch == "mobilenet_v3_large":
        m = models.mobilenet_v3_large(weights=models.MobileNet_V3_Large_Weights.DEFAULT)
    else:
        m = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
    m.classifier[3] = nn.Linear(m.classifier[3].in_features, n)
    return m


@torch.no_grad()
def embed_and_predict(model, dl, device):
    """Returns pooled embeddings (before the classifier), logits and targets."""
    model.eval()
    feats, logits, ys = [], [], []
    for x, y in dl:
        x = x.to(device)
        f = model.avgpool(model.features(x)).flatten(1)
        feats.append(f.cpu()); logits.append(model.classifier(f).cpu()); ys.append(y)
    return torch.cat(feats).numpy(), torch.cat(logits), torch.cat(ys)


def main() -> None:
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 160
    arch = sys.argv[3] if len(sys.argv) > 3 else "mobilenet_v3_small"
    random.seed(7); torch.manual_seed(7); np.random.seed(7)
    torch.set_num_threads(max(4, torch.get_num_threads()))

    classes = sorted(p.name for p in DATA.iterdir() if p.is_dir())
    idx = {c: i for i, c in enumerate(classes)}
    items = [(p, idx[c]) for c in classes for p in (DATA / c).glob("*.jpg")]
    by: dict[int, list] = defaultdict(list)
    for it in items:
        by[it[1]].append(it)
    train, val = [], []
    for y, lst in by.items():
        random.shuffle(lst)
        n_val = max(15, int(0.12 * len(lst)))
        val += lst[:n_val]; train += lst[n_val:]
    print(f"classes={len(classes)} train={len(train)} val={len(val)} size={size} arch={arch} epochs={epochs}", flush=True)

    tf_train = transforms.Compose([
        transforms.RandomResizedCrop(size, scale=(0.55, 1.0)), transforms.RandomHorizontalFlip(), transforms.RandomVerticalFlip(),
        transforms.RandomApply([transforms.ColorJitter(0.3, 0.3, 0.25, 0.04)], p=0.8), transforms.RandomApply([transforms.GaussianBlur(3)], p=0.15),
        transforms.RandomGrayscale(0.03), transforms.ToTensor(), transforms.Normalize(MEAN, STD),
    ])
    tf_val = transforms.Compose([transforms.Resize((size, size)), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    train_dl = DataLoader(Leaves(train, tf_train), batch_size=48, shuffle=True, num_workers=2, persistent_workers=True, drop_last=True)
    val_dl = DataLoader(Leaves(val, tf_val), batch_size=128, shuffle=False, num_workers=4)

    # class-balanced loss weights (sqrt-inverse frequency) so small field-photo classes are not drowned out
    counts = Counter(y for _, y in train)
    w = torch.tensor([1.0 / np.sqrt(counts[i]) for i in range(len(classes))], dtype=torch.float32)
    w = w / w.mean()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(arch, len(classes)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=2e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2.5e-3, total_steps=epochs * len(train_dl), pct_start=0.15)
    loss_fn = nn.CrossEntropyLoss(weight=w.to(device), label_smoothing=0.05)

    best = 0.0
    ckpt = OUT / "leaf_train_ckpt.pt"
    start_epoch, skip_steps = 0, 0
    if ckpt.exists():
        state = torch.load(ckpt, map_location="cpu")
        if state.get("classes") == classes and state.get("size") == size and state.get("arch") == arch:
            model.load_state_dict(state["model"]); opt.load_state_dict(state["opt"]); sched.load_state_dict(state["sched"])
            start_epoch, skip_steps, best = state["epoch"], state["step"], state.get("best", 0.0)
            print(f"resumed from checkpoint: epoch {start_epoch + 1} step {skip_steps}", flush=True)
    for epoch in range(start_epoch, epochs):
        model.train(); t0 = time.time(); running = 0.0; seen = 0
        for step, (x, y) in enumerate(train_dl):
            if epoch == start_epoch and step < skip_steps:
                continue  # the sampler is reshuffled, so this only skips the same number of steps, which is fine
            x, y = x.to(device), y.to(device)
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(model(x), y)
            loss.backward(); opt.step(); sched.step()
            running += loss.item(); seen += 1
            if (step + 1) % 100 == 0:
                print(f"  epoch {epoch + 1} step {step + 1}/{len(train_dl)} loss {running / seen:.3f} ({time.time() - t0:.0f}s)", flush=True)
            if (step + 1) % 400 == 0:
                torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(), "epoch": epoch, "step": step + 1, "best": best, "classes": classes, "size": size, "arch": arch}, ckpt)
        skip_steps = 0
        feats, logits, ys = embed_and_predict(model, val_dl, device)
        pred = logits.argmax(1)
        acc = (pred == ys).float().mean().item()
        print(f"epoch {epoch + 1}: loss {running / max(seen, 1):.3f} val_acc {acc:.4f} ({time.time() - t0:.0f}s)", flush=True)
        if acc >= best:
            best = acc
            torch.save(model.state_dict(), OUT / "leaf_mobilenetv3.pt")
            save_meta(classes, arch, size, feats, logits, ys, acc, len(train), len(val), epoch + 1)
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(), "epoch": epoch + 1, "step": 0, "best": best, "classes": classes, "size": size, "arch": arch}, ckpt)
    ckpt.unlink(missing_ok=True)
    print(f"done. best val_acc={best:.4f}", flush=True)


def save_meta(classes, arch, size, feats, logits, ys, acc, n_train, n_val, epoch):
    """Per-class accuracy plus open-set statistics from the validation embeddings."""
    ys_np = ys.numpy(); pred = logits.argmax(1).numpy()
    per_class = {}
    for i, c in enumerate(classes):
        m = ys_np == i
        per_class[c] = {"n": int(m.sum()), "acc": round(float((pred[m] == i).mean()), 4) if m.any() else None}
    other = classes.index("other") if "other" in classes else -1
    in_dist = ys_np != other
    # Mahalanobis: class means on in-distribution classes, shared covariance (Ledoit-style shrinkage for stability)
    means = np.stack([feats[ys_np == i].mean(0) if (ys_np == i).any() else feats.mean(0) for i in range(len(classes))])
    centered = np.concatenate([feats[ys_np == i] - means[i] for i in range(len(classes)) if i != other and (ys_np == i).any()])
    cov = np.cov(centered, rowvar=False)
    cov = 0.85 * cov + 0.15 * np.eye(cov.shape[0]) * np.trace(cov) / cov.shape[0]
    prec = np.linalg.inv(cov)

    def mdist(f):
        d = f[:, None, :] - means[None, :, :]
        return np.einsum("nkd,de,nke->nk", d, prec, d).min(1)

    d_in = np.sqrt(mdist(feats[in_dist]))
    d_out = np.sqrt(mdist(feats[~in_dist])) if (~in_dist).any() else np.array([])
    thr = float(np.quantile(d_in, 0.985))
    probs = torch.softmax(logits, 1).numpy()
    p_other_in = probs[in_dist, other] if other >= 0 else np.zeros(1)
    p_other_out = probs[~in_dist, other] if other >= 0 and (~in_dist).any() else np.zeros(1)
    ood = {
        "mahalanobis_threshold": thr,
        "in_dist_reject_rate_at_threshold": round(float((d_in > thr).mean()), 4),
        "ood_reject_rate_by_distance": round(float((d_out > thr).mean()), 4) if d_out.size else None,
        "ood_reject_rate_by_other_class": round(float((p_other_out > 0.5).mean()), 4) if p_other_out.size > 1 else None,
        "in_dist_false_other_rate": round(float((p_other_in > 0.5).mean()), 4),
    }
    meta = {
        "arch": arch, "size": size, "mean": MEAN, "std": STD, "labels": classes, "val_acc": round(acc, 4),
        "train_images": n_train, "val_images": n_val, "epochs": epoch, "per_class": per_class, "ood": ood,
        "other_index": other,
    }
    (OUT / "leaf_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    np.savez_compressed(OUT / "leaf_ood.npz", means=means.astype(np.float32), prec=prec.astype(np.float32))
    print("  ood:", ood, flush=True)


if __name__ == "__main__":
    main()
