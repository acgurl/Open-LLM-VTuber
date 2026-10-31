#!/usr/bin/env python3
"""Warm the CDN edge cache for every Live2D asset referenced by model_dict.json.

Run after deploying or changing a model so the first visitor does not pay for an
edge MISS back to the origin:

    python scripts/warm_live2d_cache.py
    python scripts/warm_live2d_cache.py --base-url https://vtuber.acgurl.cn

Assets are derived from each model3.json, so renamed or versioned entries are
picked up automatically. Re-run and check that cf-cache-status is HIT.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def _open(url: str, timeout: float):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=HEADERS), timeout=timeout
    )


def fetch(url: str, timeout: float) -> tuple[str, str, str]:
    with _open(url, timeout) as resp:
        resp.read()
        return (
            str(resp.status),
            resp.headers.get("cf-cache-status", "-"),
            resp.headers.get("content-length", "?"),
        )


def referenced_assets(settings_url: str, timeout: float) -> list[str]:
    with _open(settings_url, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    refs = data.get("FileReferences") or {}
    assets: list[str] = []
    if isinstance(refs.get("Moc"), str):
        assets.append(refs["Moc"])
    assets.extend(t for t in refs.get("Textures") or [] if isinstance(t, str))
    for key in ("Physics", "Pose", "DisplayInfo"):
        if isinstance(refs.get(key), str):
            assets.append(refs[key])
    for expression in refs.get("Expressions") or []:
        if isinstance(expression.get("File"), str):
            assets.append(expression["File"])
    for motions in (refs.get("Motions") or {}).values():
        for motion in motions:
            if isinstance(motion.get("File"), str):
                assets.append(motion["File"])
    return [urljoin(settings_url, asset) for asset in assets]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://vtuber.acgurl.cn")
    parser.add_argument("--model-dict", default="conf/model_dict.json")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    base = args.base_url.rstrip("/") + "/"
    dict_path = Path(args.model_dict)
    if not dict_path.is_file():
        print(f"model dict not found: {dict_path}")
        return 1

    entries = json.loads(dict_path.read_text(encoding="utf-8"))
    settings = [
        urljoin(base, entry["url"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("url"), str)
    ]

    urls: list[str] = []
    for settings_url in settings:
        urls.append(settings_url)
        urls.extend(referenced_assets(settings_url, args.timeout))
    urls = list(dict.fromkeys(urls))
    print(f"warming {len(urls)} assets for {len(settings)} models via {base}")

    def warm(url: str) -> str:
        try:
            status, cache, length = fetch(url, args.timeout)
            return f"{status} {cache:8s} {length:>9s} {url}"
        except Exception as exc:
            return f"ERR {type(exc).__name__}: {exc} {url}"

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        for line in pool.map(warm, urls):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
