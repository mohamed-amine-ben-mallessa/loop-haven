#!/usr/bin/env python3
"""Minimal LoopHaven client: search, inspect, download — stdlib only.

Run the server first:

    python -m uvicorn loophaven.api.app:app --host 127.0.0.1 --port 8000

then:

    python examples/quickstart.py
    python examples/quickstart.py --genre Phonk --bpm 140
    python examples/quickstart.py --genre Phonk --bpm 140 --download 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = os.environ.get("LOOPHAVEN_API", "http://127.0.0.1:8000").rstrip("/")


def get_json(path: str, **params):
    url = API + path
    if params:
        url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
    with urlopen(Request(url), timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def download(path: str, destination: str) -> int:
    with urlopen(Request(API + path), timeout=300) as response:
        payload = response.read()
        print("  content-type:", response.headers.get("content-type"))
        print("  filename    :", response.headers.get("content-disposition"))
    with open(destination, "wb") as handle:
        handle.write(payload)
    return len(payload)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genre", default="Trap")
    parser.add_argument("--bpm", type=int, default=140)
    parser.add_argument("--key")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--download", type=int, metavar="N",
                        help="download result N (1-based); needs `haven login`")
    parser.add_argument("--out", default="loop.wav")
    args = parser.parse_args(argv)

    print(f"→ {API}/api/search  genre={args.genre} bpm={args.bpm} key={args.key}")
    result = get_json("/api/search", genre=args.genre, bpm=args.bpm,
                      key=args.key, limit=args.limit)

    print("  upstream:", result.get("looperman_url"))
    print("  resolved:", json.dumps(result.get("resolved", {}), ensure_ascii=False))
    print(f"  {result.get('count', 0)} result(s)\n")

    for index, item in enumerate(result.get("loops", []), 1):
        print(f"{index}. {item.get('title')}")
        print(f"   {item.get('bpm')} BPM · {item.get('key')} · {item.get('genre')}"
              f" · {item.get('duration_seconds')}s · by {item.get('author')}")
        print(f"   preview: {item.get('mp3_url')}")
        print(f"   id={item.get('id')} hash={item.get('favorite_hash')}\n")

    if args.download:
        loops = result.get("loops", [])
        if not 1 <= args.download <= len(loops):
            print(f"no result #{args.download}", file=sys.stderr)
            return 2
        loop_id = loops[args.download - 1]["id"]

        # Free check: tells you the format and whether the quota allows it,
        # without spending a download.
        info = get_json(f"/api/download/info/loop/{loop_id}")
        print(f"→ would produce {info.get('expected_format')} "
              f"({info.get('size_hint')}), available={info.get('download_available')}")
        if not info.get("download_available"):
            print("  not available: run `haven login` or wait for the quota",
                  file=sys.stderr)
            return 1

        print(f"→ downloading loop {loop_id} (this spends one quota credit)")
        size = download(f"/api/download/audio/loop/{loop_id}", args.out)
        print(f"  wrote {args.out} ({size / 1024 / 1024:.2f} MB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
