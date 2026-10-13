"""Download every parquet file of a public Hugging Face dataset (no token) into data/raw/<owner__name>/.

    python scripts/fetch_hf_parquet.py <owner/name> [max_files] [workers]

Uses the repo's own parquet files via /resolve/ URLs, validates each file by opening its parquet footer,
and re-downloads anything corrupt. Files that already validate are skipped, so it is safe to rerun.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent


def valid(path: Path) -> bool:
    try:
        pq.ParquetFile(path).metadata  # noqa: B018
        return True
    except Exception:  # noqa: BLE001
        return False


def fetch(ds: str, rfile: str, dest: Path) -> str:
    url = f"https://huggingface.co/datasets/{ds}/resolve/main/{rfile}"
    if dest.exists() and valid(dest):
        return f"skip {dest.name}"
    for attempt in range(6):
        t = time.time()
        try:
            with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True) as c:
                with c.stream("GET", url) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(8 << 20):
                            f.write(chunk)
            if valid(tmp):
                tmp.replace(dest)
                return f"{dest.name}: {dest.stat().st_size/1e6:.0f} MB in {time.time()-t:.0f}s"
            tmp.unlink(missing_ok=True)
            raise OSError("corrupt parquet after download")
        except (httpx.HTTPError, OSError) as exc:
            time.sleep(4 * (attempt + 1))
            last = f"{type(exc).__name__}: {exc}"
    return f"FAILED {dest.name}: {last}"


def main() -> None:
    ds = sys.argv[1]
    max_files = int(sys.argv[2]) if len(sys.argv) > 2 else 10**6
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    out = ROOT / "data" / "raw" / ds.replace("/", "__")
    out.mkdir(parents=True, exist_ok=True)
    info = httpx.get(f"https://huggingface.co/api/datasets/{ds}", timeout=60, follow_redirects=True).json()
    files = sorted(s["rfilename"] for s in info.get("siblings", []) if s["rfilename"].endswith(".parquet"))[:max_files]
    print(f"{ds}: {len(files)} parquet files", flush=True)
    jobs = [(ds, rf, out / rf.replace("/", "__")) for rf in files]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for msg in ex.map(lambda j: fetch(*j), jobs):
            print("  " + msg, flush=True)
    bad = [p for p in out.glob("*.parquet") if not valid(p)]
    for p in bad:
        p.unlink()
    print(f"done; {len(list(out.glob('*.parquet')))} valid files, removed {len(bad)} corrupt", flush=True)


if __name__ == "__main__":
    main()
