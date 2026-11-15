"""LoopHaven CLI: search, JSON output, preview playback, account session, and small ZIP exports."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import webbrowser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_API = os.environ.get("LOOPHAVEN_API", "http://127.0.0.1:8000").rstrip("/")


def request(api: str, path: str, *, params=None, payload=None, raw=False):
    url = f"{api.rstrip('/')}{path}"
    if params:
        url += "?" + urlencode(params, doseq=True)
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {}, method="POST" if data else "GET")
    try:
        with urlopen(req, timeout=90) as response:
            body = response.read()
            return body if raw else json.loads(body.decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"API {exc.code}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"API unreachable ({url}). Start LoopHaven first: {exc}") from exc


def build_parser():
    parser = argparse.ArgumentParser(prog="haven", description="LoopHaven - search and pack Looperman loops")
    parser.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default: {DEFAULT_API})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", aliases=["find"], help="Search loops or acapellas; --json is agent-friendly")
    p_search.add_argument("--kind", choices=["loops", "acapellas"], default="loops")
    p_search.add_argument("--genre")
    p_search.add_argument("--category")
    p_search.add_argument("--key")
    p_search.add_argument("--bpm", type=int)
    p_search.add_argument("--ftempo", type=int)
    p_search.add_argument("--ttempo", type=int)
    p_search.add_argument("--keyword")
    p_search.add_argument("--tsig")
    p_search.add_argument("--mid")
    p_search.add_argument("--who", type=int, choices=[1, 2])
    p_search.add_argument("--ppage", type=int, choices=[25, 50, 100])
    p_search.add_argument("--when")
    p_search.add_argument("--order", default="date")
    p_search.add_argument("--dir", choices=["d", "a"], default="d")
    p_search.add_argument("--mf", type=int, choices=[1, 2], help="Acapella: 1 male, 2 female")
    p_search.add_argument("--style", type=int, choices=[1, 2, 3], help="Acapella vocal style filter")
    p_search.add_argument("--vocal-type", type=int, choices=[1, 2, 3, 4, 5])
    p_search.add_argument("--ur", type=int, choices=[1, 2, 3], help="Acapella licence filter")
    p_search.add_argument("--autotune", type=int, choices=[1, 2])
    p_search.add_argument("--favs", action="store_true", help="Search only your favourites (requires a session)")
    p_search.add_argument("--mydl", action="store_true", help="Acapellas you already downloaded")
    p_search.add_argument("--page", type=int, default=1)
    p_search.add_argument("--limit", type=int, default=4)
    p_search.add_argument("--json", action="store_true", help="Print full JSON for agents and pipelines")

    p_zip = sub.add_parser("zip", help="Export a ZIP of 2 to 4 selected loops")
    p_zip.add_argument("--ids", nargs="+", required=True)
    p_zip.add_argument("--format", choices=["mp3", "wav"], default="mp3")
    p_zip.add_argument("--output", default="loop-haven-pack.zip")

    p_play = sub.add_parser("play", help="Open an audio preview in the browser")
    p_play.add_argument("--url", help="Preview MP3 URL from the JSON results")
    p_play.add_argument("--id", help="Looperman item id")
    p_play.add_argument("--kind", choices=["loop", "acapella"], default="loop")

    p_fav = sub.add_parser("fav", help="Add or remove a Looperman favourite (toggle)")
    p_fav.add_argument("--hash", required=True, help="favorite_hash returned by a search")
    p_fav.add_argument("--type", choices=["loop", "acapella", "track"], required=True)

    sub.add_parser("login", help="Open a local session; the password is not stored")
    sub.add_parser("logout", help="Close the local session")
    sub.add_parser("status", help="Show the session state without printing the email")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    api = args.api
    try:
        if args.command in {"search", "find"}:
            names = ["genre", "category", "key", "bpm", "ftempo", "ttempo", "keyword", "tsig", "mid", "who", "ppage", "when", "order", "dir", "mf", "style", "vocal_type", "ur", "autotune", "favs", "mydl", "page", "limit"]
            params = {}
            for name in names:
                value = getattr(args, name, None)
                if value is not None and value is not False:
                    params[name] = value
            if args.kind == "acapellas":
                path = "/api/acapellas/search"
                if "category" in params:
                    parser.error("--category applies to loops, not to acapellas")
            else:
                path = "/api/search"
                for unsupported in ("mf", "style", "vocal_type", "ur", "autotune", "mydl"):
                    params.pop(unsupported, None)
            result = request(api, path, params=params)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            items = result.get("acapellas", []) if args.kind == "acapellas" else result.get("loops", [])
            print(f"{len(items)} result(s) - {result.get('looperman_url', '')}")
            for i, item in enumerate(items, 1):
                pieces = [f"{i}. {item.get('title', '(untitled)')}"]
                if item.get("author"): pieces.append(f"by {item['author']}")
                if item.get("bpm"): pieces.append(f"{item['bpm']} BPM")
                if item.get("key"): pieces.append(str(item['key']))
                if item.get("genre"): pieces.append(str(item['genre']))
                if item.get("license"): pieces.append(f"licence: {item['license']}")
                print(" - ".join(pieces))
                print(f"   id={item.get('id')} hash={item.get('favorite_hash')} preview={item.get('mp3_url')}")
            if args.kind == "acapellas":
                print("MP3 URLs are previews; check the licence before any use. Full acapella export is not enabled.")
            return 0

        if args.command == "zip":
            if not 2 <= len(args.ids) <= 4:
                parser.error("a ZIP must contain 2 to 4 ids")
            if any(not str(loop_id).isdigit() for loop_id in args.ids):
                parser.error("ids must be numeric")
            content = request(api, "/api/download/zip", payload={"ids": args.ids, "format": args.format, "filename": Path(args.output).name}, raw=True)
            Path(args.output).write_bytes(content)
            print(f"ZIP written: {args.output} ({len(content)} bytes)")
            return 0

        if args.command == "play":
            url = args.url
            if not url and args.id:
                if not args.id.isdigit():
                    parser.error("the id must be numeric")
                detail_path = f"/api/loop/{args.id}" if args.kind == "loop" else f"/api/acapellas/{args.id}"
                detail = request(api, detail_path)
                url = detail.get("mp3_url") or (detail.get("data") or {}).get("contentUrl")
                if not url:
                    raise RuntimeError("no MP3 preview URL found in the detail response")
            if not url:
                parser.error("pass --url or --id")
            if not url.startswith("https://www.looperman.com/media/"):
                parser.error("the URL must be an HTTPS Looperman media preview")
            webbrowser.open(url)
            print(f"Preview opened: {url}")
            return 0

        if args.command == "fav":
            result = request(api, "/api/favorites/toggle", payload={"item_hash": args.hash, "item_type": args.type})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "login":
            email = input("Looperman email: ").strip()
            password = getpass.getpass("Looperman password (not stored): ")
            result = request(api, "/api/auth/login", payload={"email": email, "password": password})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "logout":
            print(json.dumps(request(api, "/api/auth/logout", payload={}), ensure_ascii=False, indent=2))
            return 0

        if args.command == "status":
            print(json.dumps(request(api, "/api/auth/status"), ensure_ascii=False, indent=2))
            return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"haven: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
