"""Optional MCP tools backed by the local LoopHaven HTTP API.

Install with: pip install 'loophaven[mcp]'
Run with: loophaven-mcp
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

API = os.environ.get("LOOPHAVEN_API", "http://127.0.0.1:8000").rstrip("/")
server = FastMCP("LoopHaven")


def _call(path: str, *, params=None, payload=None, raw=False):
    url = API + path
    if params:
        url += "?" + urlencode(params)
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
    with urlopen(request, timeout=90) as response:
        content = response.read()
        return content if raw else json.loads(content.decode("utf-8"))


@server.tool()
def search_loops(genre: str | None = None, category: str | None = None,
                bpm: int | None = None, key: str | None = None,
                keyword: str | None = None, tsig: str | None = None,
                limit: int = 4, favs: bool = False) -> str:
    """Search Looperman loops. `limit` is the result count, not the ZIP size."""
    params = {k: v for k, v in locals().copy().items()
              if k in {"genre", "category", "bpm", "key", "keyword", "tsig", "limit", "favs"} and v is not None and v is not False}
    return json.dumps(_call("/api/search", params=params), ensure_ascii=False)


@server.tool()
def search_acapellas(genre: str | None = None, bpm: int | None = None,
                     key: str | None = None, male_or_female: int | None = None,
                     vocal_style: int | None = None, licence: int | None = None,
                     keyword: str | None = None, limit: int = 4) -> str:
    """Search acapellas and return public preview URLs plus the listed licence label."""
    values = {"genre": genre, "bpm": bpm, "key": key, "mf": male_or_female,
              "style": vocal_style, "ur": licence, "keyword": keyword, "limit": limit}
    params = {k: v for k, v in values.items() if v is not None}
    return json.dumps(_call("/api/acapellas/search", params=params), ensure_ascii=False)


@server.tool()
def get_acapella_detail(acapella_id: str) -> str:
    """Get acapella metadata, public preview, and the Looperman usage/licence notice."""
    return json.dumps(_call(f"/api/acapellas/{acapella_id}"), ensure_ascii=False)


@server.tool()
def get_preview_url(item_id: str, kind: str = "loop") -> str:
    """Return a public MP3 preview URL for a loop or acapella."""
    if not item_id.isdigit() or kind not in {"loop", "acapella"}:
        raise ValueError("Use a numeric item_id and kind loop|acapella")
    path = f"/api/loop/{item_id}" if kind == "loop" else f"/api/acapellas/{item_id}"
    detail = _call(path)
    preview = detail.get("mp3_url") or (detail.get("data") or {}).get("contentUrl")
    if not preview:
        raise ValueError("No public preview URL in detail")
    return preview


@server.tool()
def export_loop_zip(ids: list[str], format: str = "mp3") -> str:
    """Create a personal ZIP of 2–4 selected loops; WAV requires login."""
    if not 2 <= len(ids) <= 4 or any(not item_id.isdigit() for item_id in ids):
        raise ValueError("Supply 2–4 numeric loop IDs")
    if format not in {"mp3", "wav"}:
        raise ValueError("format must be mp3 or wav")
    content = _call("/api/download/zip", payload={"ids": ids, "format": format}, raw=True)
    from pathlib import Path
    destination = Path.home() / "loop-haven-downloads" / f"loop-haven-{format}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return str(destination)


@server.tool()
def toggle_favorite(item_hash: str, item_type: str) -> str:
    """Add or remove an item from the logged-in account's favorites (state toggle)."""
    return json.dumps(_call("/api/favorites/toggle", payload={"item_hash": item_hash, "item_type": item_type}), ensure_ascii=False)


def main():
    server.run()


if __name__ == "__main__":
    main()
