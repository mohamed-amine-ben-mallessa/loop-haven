from fastapi import FastAPI, Query, HTTPException, Request, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, RedirectResponse
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from contextlib import asynccontextmanager
import asyncio
import requests
import zipfile
import io
import re
import time
import os
from urllib.parse import urlparse
from ..providers.looperman.scraper import (
    scrape_loops,
    scrape_acapellas,
    build_search_url,
    build_acapella_search_url,
    get_acapella_detail,
    get_loop_detail,
    resolve_download,
    download_media,
    media_filename,
    extract_download_link,
    LoopermanError,
    RateLimited,
    NotAudio,
    HEADERS,
    BASE,
    rate_limit_state,
)
from ..providers.looperman import auth, filters
from ..providers.looperman.filters import UnknownFilter

@asynccontextmanager
async def lifespan(application):
    # Reuse the persisted Looperman cookie (or env credentials) so restarting
    # the service no longer silently drops the WAV download capability.
    try:
        await asyncio.to_thread(auth.ensure_login)
    except Exception:
        pass
    yield


app = FastAPI(
    title="LoopHaven API",
    description=(
        "Unofficial local API for Looperman loops and acapella previews: "
        "filtered search, item detail, media download and personal ZIP packs."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8765", "http://127.0.0.1:8765", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class LoginRequest(BaseModel):
    email: str
    password: str

class ZipRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)
    format: str = "mp3"  # mp3 or wav
    # Optional search result objects; metadata is reused for filenames and source URLs.
    loops: Optional[List[dict]] = None
    filename: Optional[str] = None

class FavoriteToggleRequest(BaseModel):
    item_hash: str
    item_type: str

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOTYPE_PAGE = PROJECT_ROOT / "web" / "prototype" / "index.html"

@app.get("/", include_in_schema=False)
def root():
    # In a source checkout, serve the prototype on the same origin as /api so its
    # search, auth, and audio requests work without a separate frontend server.
    if PROTOTYPE_PAGE.is_file():
        return FileResponse(PROTOTYPE_PAGE)
    return RedirectResponse(url="/docs")

@app.get("/api/health")
def health():
    status = auth.get_status()
    status.pop("email", None)
    return {
        "status": "ok",
        "message": "LoopHaven API proxy ready",
        "base": BASE,
        "auth": status,
        "rate_limit": rate_limit_state(),
    }

@app.get("/api/genres")
def genres():
    return {
        "genres": [
            {"name": "Trap", "count": 95898, "slug": "trap"},
            {"name": "Hip Hop", "count": 34548, "slug": "hip-hop"},
            {"name": "House", "count": 3185, "slug": "house"},
            {"name": "Techno", "count": 2410, "slug": "techno"},
            {"name": "Dubstep", "count": 3326, "slug": "dubstep"},
            {"name": "Drum And Bass", "count": 1882, "slug": "drum-and-bass"},
            {"name": "EDM", "count": 1860, "slug": "edm"},
            {"name": "Electronic", "count": 6599, "slug": "electronic"},
            {"name": "Ambient", "count": 6888, "slug": "ambient"},
            {"name": "Lo-Fi", "count": 4596, "slug": "lo-fi"},
            {"name": "Phonk", "count": 1262, "slug": "phonk"},
            {"name": "Afrobeat", "count": 734, "slug": "afrobeat"},
            {"name": "Boom Bap", "count": 2096, "slug": "boom-bap"},
            {"name": "RnB", "count": 6987, "slug": "rnb"},
            {"name": "Pop", "count": 4985, "slug": "pop"},
            {"name": "Rock", "count": 3053, "slug": "rock"},
            {"name": "Cinematic", "count": 3114, "slug": "cinematic"},
            {"name": "Jazz", "count": 1142, "slug": "jazz"},
            {"name": "Funk", "count": 1115, "slug": "funk"},
            {"name": "Deep House", "count": 1001, "slug": "deep-house"},
            {"name": "Reggaeton", "count": 1253, "slug": "reggaeton"},
            {"name": "Dancehall", "count": 613, "slug": "dancehall"},
            {"name": "Trance", "count": 2098, "slug": "trance"},
            {"name": "Chill Out", "count": 5199, "slug": "chill-out"},
        ]
    }

@app.get("/api/categories")
def categories():
    return {
        "categories": [
            {"name": "Piano", "count": 36875},
            {"name": "Synth", "count": 51142},
            {"name": "Drum", "count": 37838},
            {"name": "Bass Synth", "count": 5502},
            {"name": "Bass Guitar", "count": 1415},
            {"name": "Bells", "count": 15759},
            {"name": "Guitar Acoustic", "count": 16380},
            {"name": "Guitar Electric", "count": 19393},
            {"name": "Strings", "count": 5969},
            {"name": "Pad", "count": 12280},
            {"name": "Vocal", "count": 4761},
            {"name": "Brass", "count": 2674},
            {"name": "Flute", "count": 4243},
            {"name": "Organ", "count": 1613},
            {"name": "Percussion", "count": 2546},
            {"name": "Fx", "count": 2118},
            {"name": "Harp", "count": 1268},
            {"name": "Violin", "count": 1427},
            {"name": "Wobble Bass", "count": 1417},
            {"name": "Choir", "count": 2371},
            {"name": "Arpeggio", "count": 1496},
        ]
    }

@app.get("/api/keys")
def keys():
    return {"keys": ["C","Cm","C#","C#m","D","Dm","D#","D#m","E","Em","F","Fm","F#","F#m","G","Gm","G#","G#m","A","Am","A#","A#m","B","Bm","Unknown"]}

@app.post("/api/auth/login")
def login_endpoint(payload: LoginRequest):
    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="email and password are required")
    result = auth.login(payload.email, payload.password)
    if result.get("success"):
        result.pop("email", None)
        result["message"] = f"Session Looperman ouverte{': ' + result['username'] if result.get('username') and '@' not in result['username'] else ''}."
        return result
    else:
        raise HTTPException(status_code=401, detail=result.get("error", "Login failed"))

@app.get("/api/auth/status")
def auth_status():
    status = auth.get_status()
    status.pop("email", None)
    return status

@app.post("/api/auth/logout")
def auth_logout():
    return auth.logout()

@app.post("/api/favorites/toggle")
def toggle_favorite(payload: FavoriteToggleRequest):
    """Toggle an existing Looperman favorite; only runs after an explicit caller request."""
    if not auth.is_logged_in():
        raise HTTPException(status_code=401, detail="open a Looperman session first")
    if not re.fullmatch(r"[A-Za-z0-9]{1,64}", payload.item_hash or ""):
        raise HTTPException(status_code=422, detail="invalid item_hash")
    if payload.item_type not in {"loop", "acapella", "track"}:
        raise HTTPException(status_code=422, detail="item_type must be loop, acapella or track")
    page_by_type = {"loop": "/loops", "acapella": "/acapellas", "track": "/tracks/featured"}
    session = auth.authenticated_session()
    try:
        page = session.get(BASE + page_by_type[payload.item_type], headers=HEADERS, timeout=15)
        page.raise_for_status()
        token_match = re.search(r"csrfToken\s*=\s*['\"]([A-Za-z0-9]+)['\"]", page.text)
        if not token_match:
            raise HTTPException(status_code=502, detail="Looperman CSRF token not found; nothing was sent")
        headers = {**HEADERS, "Origin": BASE, "Referer": page.url,
                   "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
        response = session.post(
            BASE + "/ajax/ajax_favs",
            data={"item_hash": payload.item_hash, "item_type": payload.item_type,
                  "csrftoken": token_match.group(1)},
            headers=headers, timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="unexpected Looperman response")
        return {"success": data.get("fail") is False, "item_hash": payload.item_hash,
                "item_type": payload.item_type, "is_favorite": data.get("isfav"),
                "total_favorites": data.get("total_favs"), "upstream": data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Looperman favourite action failed: {exc}")

def _filter_error(exc):
    """422 that says which value failed and what Looperman accepts instead."""
    return HTTPException(status_code=422, detail={
        "error": "unknown filter",
        "filter": exc.name,
        "value": exc.value,
        "suggestions": exc.suggestions,
        "catalogue": "/api/filters",
    })


def _resolved(values):
    """Drop None entries so the echo only shows filters that were applied."""
    return {name: {"id": key_id, "label": label}
            for name, (key_id, label) in values.items() if key_id is not None}


@app.get("/api/filters")
def filter_catalogue():
    """The filter vocabulary Looperman's own advanced-search form submits.

    Reversed from POST /ajax/ajax_adv_search_modal; use these ids instead of
    guessing slugs. `did` (DAW) is absent on purpose: it is a card field, not a
    filter, and Looperman ignores it.
    """
    return {"success": True, **filters.catalogue()}


@app.get("/api/search")
def search(
    genre: str = Query(None),
    category: str = Query(None),
    key: str = Query(None),
    bpm: int = Query(None),
    ftempo: int = Query(None),
    ttempo: int = Query(None),
    keyword: str = Query(None),
    order: str = Query("date"),
    dir: str = Query("d"),
    limit: int = Query(10, ge=1, le=50),
    page: int = Query(1, ge=1),
    when: str = Query(None),
    tsig: Optional[str] = Query(None),
    mid: Optional[str] = Query(None, pattern=r"^\d+$"),
    who: Optional[int] = Query(None, ge=1, le=2),
    ppage: Optional[int] = Query(None, ge=25, le=100),
    favs: bool = Query(False)
):
    if dir not in {"d", "a"}:
        raise HTTPException(status_code=422, detail="dir must be d (descending) or a (ascending)")
    if order not in filters.ORDERS:
        raise HTTPException(status_code=422,
                            detail=f"invalid order; values: {', '.join(filters.ORDERS)}")
    if ppage is not None and ppage not in filters.PER_PAGE.values():
        raise HTTPException(status_code=422, detail="ppage must be 25, 50 or 100")
    if bpm and not ftempo:
        ftempo = bpm
        ttempo = bpm
    if ftempo and not ttempo:
        ttempo = ftempo
    try:
        url = build_search_url(genre=genre, category=category, key=key, ftempo=ftempo,
                               ttempo=ttempo, keyword=keyword, order=order, direction=dir,
                               page=page, when=when, tsig=tsig, mid=mid, who=who,
                               ppage=ppage, favs=favs)
    except UnknownFilter as exc:
        raise _filter_error(exc)
    # Use authenticated session if logged in to get WAV links if available
    # Pass session hint to scraper via auth flag
    try:
        result = scrape_loops(url, limit=limit, use_auth=auth.is_logged_in())
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return {
        "success": True,
        "query": {"genre": genre, "category": category, "key": key, "bpm": bpm or ftempo, "ftempo": ftempo, "ttempo": ttempo, "keyword": keyword, "limit": limit, "page": page, "order": order, "tsig": tsig, "mid": mid, "who": who, "ppage": ppage, "favs": favs},
        "resolved": _resolved({
            "genre": filters.resolve_genre(genre),
            "category": filters.resolve_category(category),
            "key": filters.resolve_key(key),
            "time_signature": filters.resolve_time_signature(tsig),
            "when": filters.resolve_choice("when", when, filters.WHEN),
            "who": filters.resolve_choice("who", who, filters.WHO),
        }),
        "looperman_url": url,
        "count": result.get("count", 0),
        "total": result.get("total_found"),
        "pagination": result.get("page"),
        "loops": result.get("loops", []),
        "info": "MP3 previews need no session. WAV requires a session (POST /api/auth/login).",
        "auth": {k: v for k, v in auth.get_status().items() if k != "email"},
    }

@app.get("/api/acapellas/search")
def search_acapellas(
    genre: Optional[str] = Query(None),
    category: Optional[str] = Query(None, description="does not exist for acapellas; rejected with 422"),
    key: Optional[str] = Query(None),
    bpm: Optional[int] = Query(None, ge=40, le=220),
    ftempo: Optional[int] = Query(None, ge=40, le=220),
    ttempo: Optional[int] = Query(None, ge=40, le=220),
    keyword: Optional[str] = Query(None, max_length=120),
    tsig: Optional[str] = Query(None),
    mid: Optional[str] = Query(None, pattern=r"^\d+$"),
    rights: Optional[int] = Query(None, ge=1, le=2, description="1 = commercial use allowed, 2 = non-commercial only"),
    ur: Optional[int] = Query(None, ge=1, le=2, description="raw Looperman name for `rights`"),
    autotune: Optional[int] = Query(None, ge=1, le=2, description="1 = no autotune, 2 = autotune used"),
    mf: Optional[int] = Query(None, ge=1, le=3, description="1 = male, 2 = female, 3 = both"),
    style: Optional[int] = Query(None, ge=1, le=3, description="1 = rap, 2 = singing, 3 = both"),
    vocal_type: Optional[int] = Query(None, ge=1, le=3, description="1 = hook, 2 = verse, 3 = full song"),
    adult: Optional[str] = Query(None, pattern="^[yn]$", description="y = keep adult content, n = exclude it"),
    who: Optional[int] = Query(None, ge=1, le=2),
    when: Optional[str] = Query(None, description="1=24h, 5=48h, 2=7d, 3=30d, 4=60d"),
    order: str = Query("date"),
    dir: str = Query("d", pattern="^[da]$"),
    page: int = Query(1, ge=1),
    ppage: Optional[int] = Query(None, ge=25, le=100),
    favs: bool = Query(False),
    mydl: bool = Query(False),
    limit: int = Query(10, ge=1, le=50),
):
    if dir not in {"d", "a"}:
        raise HTTPException(status_code=422, detail="dir must be d (descending) or a (ascending)")
    if category is not None:
        # Looperman ignores ?cid= on acapella listings and still returns
        # results, which looks like a working filter. Reject it instead of
        # returning a silently unfiltered page.
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unknown filter",
                "filter": "category",
                "value": category,
                "message": (
                    "category does not exist for acapellas (it is a loops-only filter). "
                    "Remove ?category= or use genre instead."
                ),
                "catalogue": "/api/filters",
            },
        )
    if order not in filters.ORDERS:
        raise HTTPException(status_code=422,
                            detail=f"invalid order; values: {', '.join(filters.ORDERS)}")
    if ppage is not None and ppage not in filters.PER_PAGE.values():
        raise HTTPException(status_code=422, detail="ppage must be 25, 50 or 100")
    if bpm is not None and ftempo is None:
        ftempo, ttempo = bpm, bpm
    if ftempo is not None and ttempo is None:
        ttempo = ftempo
    # "ur" is the raw Looperman name, `rights` is the readable alias.
    usage = rights if rights is not None else ur
    try:
        upstream_url = build_acapella_search_url(
            genre=genre, key=key, ftempo=ftempo, ttempo=ttempo, keyword=keyword,
            tsig=tsig, mid=mid, ur=usage, autotune=autotune, mf=mf, style=style,
            vocal_type=vocal_type, adult=adult, when=when, who=who, order=order,
            direction=dir, page=page, ppage=ppage, favs=favs, mydl=mydl,
        )
    except UnknownFilter as exc:
        raise _filter_error(exc)
    try:
        result = scrape_acapellas(upstream_url, limit=limit, use_auth=auth.is_logged_in())
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return {
        "success": True,
        "query": {"genre": genre, "key": key, "bpm": bpm or ftempo, "ftempo": ftempo,
                  "ttempo": ttempo, "keyword": keyword, "tsig": tsig, "mid": mid,
                  "rights": usage, "autotune": autotune, "mf": mf, "style": style,
                  "type": vocal_type, "adult": adult, "who": who, "when": when,
                  "page": page, "limit": limit, "favs": favs, "mydl": mydl},
        "resolved": _resolved({
            "genre": filters.resolve_genre(genre),
            "key": filters.resolve_key(key),
            "time_signature": filters.resolve_time_signature(tsig),
            "rights": filters.resolve_choice("rights", usage, filters.USAGE_RIGHTS),
            "genders": filters.resolve_choice("genders", mf, filters.VOCAL_GENDERS),
            "style": filters.resolve_choice("style", style, filters.VOCAL_STYLES),
            "type": filters.resolve_choice("type", vocal_type, filters.VOCAL_TYPES),
            "autotune": filters.resolve_choice("autotune", autotune, filters.AUTOTUNE),
            "adult": filters.resolve_choice("adult", adult, filters.ADULT),
            "when": filters.resolve_choice("when", when, filters.WHEN),
        }),
        "looperman_url": upstream_url,
        "count": result.get("count", 0),
        "total": result.get("total_found"),
        "pagination": result.get("page"),
        "acapellas": result.get("acapellas", []),
        "note": "mp3_url is a public preview. The full file comes from /api/download/audio/acapella/{id} (MP3, Looperman daily quota).",
    }


@app.get("/api/acapellas/{acapella_id}")
def acapella_detail(acapella_id: str):
    if not re.fullmatch(r"\d+", acapella_id):
        raise HTTPException(status_code=422, detail="acapella_id must be numeric")
    result = get_acapella_detail(acapella_id, use_auth=auth.is_logged_in())
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.get("/api/loop/{loop_id}")
def loop_detail(loop_id: str):
    if not re.fullmatch(r"\d+", loop_id):
        raise HTTPException(status_code=422, detail="loop_id must be numeric")
    return get_loop_detail(loop_id, use_auth=auth.is_logged_in())

@app.get("/api/download/proxy")
def download_proxy(url: str = Query(...)):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"looperman.com", "www.looperman.com"} or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="URL must be an HTTPS Looperman URL")
    try:
        sess = auth.authenticated_session() if auth.is_logged_in() else requests
        hdr = {**HEADERS, "Referer": "https://www.looperman.com/"} if "media" in url else HEADERS
        # Media URLs may bounce to a CDN path before serving: follow while the
        # host stays on Looperman instead of rejecting every redirect.
        r = sess.get(url, headers=hdr, stream=True, timeout=30, allow_redirects=True)
        final = urlparse(r.url)
        if final.hostname not in {"looperman.com", "www.looperman.com"}:
            r.close()
            raise HTTPException(status_code=502, detail="redirect outside looperman.com refused")
        if r.status_code == 429:
            r.close()
            raise HTTPException(status_code=429, detail="Looperman download limit reached (retry in 24h)")
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
        if ctype.startswith("text/") or ctype == "application/json":
            body = next(r.iter_content(300), b"")
            r.close()
            if "limit" in body.decode("latin-1", "replace").lower():
                raise HTTPException(status_code=429, detail="Looperman download limit reached (retry in 24h)")
            raise HTTPException(status_code=502, detail=f"Looperman returned {ctype} instead of a file")
        headers = {"Content-Disposition": f'attachment; filename="{media_filename(r, url.split("/")[-1].split("?")[0])}"'}
        if r.headers.get("content-length"):
            headers["Content-Length"] = r.headers["content-length"]

        def proxy_chunks():
            try:
                yield from r.iter_content(chunk_size=8192)
            finally:
                r.close()

        return StreamingResponse(proxy_chunks(), media_type=ctype or "application/octet-stream", headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stream/preview")
def stream_preview(url: str = Query(...), range_header: Optional[str] = Header(None, alias="Range")):
    """Stream a public Looperman MP3 preview inline for browser audio players."""
    parsed = urlparse(url)
    valid_media_path = parsed.path.startswith(("/media/loops/", "/media/acapellas/"))
    if parsed.scheme != "https" or parsed.hostname not in {"looperman.com", "www.looperman.com"} or parsed.username or parsed.password or not valid_media_path:
        raise HTTPException(status_code=400, detail="only HTTPS Looperman preview URLs are allowed")
    headers = {**HEADERS, "Referer": "https://www.looperman.com/", "Accept": "audio/*,*/*;q=0.8"}
    if range_header and re.fullmatch(r"bytes=\d*-\d*", range_header):
        headers["Range"] = range_header
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=30, allow_redirects=False)
        if response.is_redirect:
            response.close()
            raise HTTPException(status_code=502, detail="Looperman redirect refused")
        if response.status_code >= 400:
            response.close()
            raise HTTPException(status_code=502, detail=f"Looperman preview answered HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "audio/mpeg")
        if "text/html" in content_type.lower():
            response.close()
            raise HTTPException(status_code=502, detail="Looperman returned an HTML page instead of the audio preview")
        forwarded = {"Accept-Ranges": response.headers.get("Accept-Ranges", "bytes"), "Cache-Control": "no-store"}
        for name in ("Content-Length", "Content-Range", "ETag", "Last-Modified"):
            if response.headers.get(name):
                forwarded[name] = response.headers[name]

        def chunks():
            try:
                yield from response.iter_content(chunk_size=64 * 1024)
            finally:
                response.close()

        return StreamingResponse(chunks(), status_code=response.status_code, media_type=content_type.split(";", 1)[0], headers=forwarded)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"preview streaming failed: {e}")

def extract_wav_url_from_page(html, loop_id=None):
    """Kept for the ZIP path: the h1-scoped /getfiles link of the page's own item."""
    return extract_download_link(html, loop_id)


def _download_response(kind, item_id):
    """Resolve the item's download link and return a validated streaming response."""
    if not auth.is_logged_in():
        raise HTTPException(status_code=401, detail="not logged in - POST /api/auth/login first")
    try:
        link, referer = resolve_download(kind, item_id)
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except LoopermanError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    parsed = urlparse(link)
    if parsed.scheme != "https" or parsed.hostname not in {"looperman.com", "www.looperman.com"}:
        raise HTTPException(status_code=502, detail="download link outside looperman.com; refused")
    try:
        return download_media(link, referer=referer)
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except NotAudio as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except LoopermanError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"download failed: {exc}")


def _stream_media(kind, item_id):
    upstream = _download_response(kind, item_id)
    content_type = (upstream.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
    extension = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
                 "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/flac": "flac",
                 "audio/ogg": "ogg"}.get(content_type, "bin")
    filename = media_filename(upstream, f"looperman-{item_id}.{extension}")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        # Tell clients what they actually got: acapellas are served as MP3 by
        # Looperman even when the caller asked for the "wav" route.
        "X-Audio-Format": extension,
        "Cache-Control": "no-store",
    }
    if upstream.headers.get("content-length"):
        headers["Content-Length"] = upstream.headers["content-length"]

    def chunks():
        try:
            yield from upstream.iter_content(chunk_size=64 * 1024)
        finally:
            upstream.close()

    return StreamingResponse(chunks(), media_type=content_type, headers=headers)


@app.get("/api/download/wav/{loop_id}")
def download_wav(loop_id: str):
    """Download a loop. Returns the upstream file as-is (WAV for loops)."""
    if not re.fullmatch(r"\d+", loop_id):
        raise HTTPException(status_code=422, detail="loop_id must be numeric")
    return _stream_media("loops", loop_id)


@app.get("/api/download/audio/{kind}/{item_id}")
def download_audio(kind: str, item_id: str):
    """Download loops or acapellas. `kind` is loop|loops|acapella|acapellas.

    Acapellas come back as MP3 (Looperman does not distribute them as WAV);
    the response says so in Content-Type and X-Audio-Format instead of lying
    with an audio/wav header and a .wav filename.
    """
    if kind not in {"loop", "loops", "acapella", "acapellas"}:
        raise HTTPException(status_code=422, detail="kind must be loop or acapella")
    if not re.fullmatch(r"\d+", item_id):
        raise HTTPException(status_code=422, detail="item_id must be numeric")
    return _stream_media("acapellas" if kind.startswith("acap") else "loops", item_id)

@app.post("/api/download/zip")
def download_zip(payload: ZipRequest):
    """
    Build a ZIP of 2-4 loops as MP3 or WAV (WAV needs a session)
    Payload: {ids: ["435165", "435157"], format: "mp3"|"wav"}
    """
    if not payload.ids and not payload.loops:
        raise HTTPException(status_code=400, detail="ids or loops required")
    selected_count = len(payload.loops) if payload.loops is not None else len(payload.ids)
    if selected_count < 2 or selected_count > 4:
        raise HTTPException(status_code=400, detail="select between 2 and 4 files")
    ids = payload.ids
    if payload.loops:
        # If loops objects provided, use them directly
        loops_data = payload.loops
        # Build ids from them if needed
        if not ids:
            ids = [str(l.get("id")) for l in loops_data]
    else:
        loops_data = None

    fmt = payload.format.lower()
    if fmt not in ["mp3","wav"]:
        raise HTTPException(status_code=400, detail="format must be mp3 or wav")
    if fmt == "wav" and not auth.is_logged_in():
        raise HTTPException(status_code=401, detail="WAV requires a session - POST /api/auth/login")

    # If we have loops_data with mp3_url already, we can use them without re-fetch
    # Otherwise, we need to fetch each loop's info
    # For mp3, we can fetch via search fallback or direct mp3 pattern: https://www.looperman.com/media/loops/{user_id}/looperman-l-{user_id}-{id padded}.mp3
    # But better to require loops_data or fetch via detail

    # Build download list
    download_items = []  # list of (filename, url, is_wav)
    pre_errors = []  # files deliberately omitted rather than substituting a different format

    # If we have loops_data with mp3_url, use it
    if loops_data:
        for loop in loops_data:
            lid = str(loop.get("id"))
            title = re.sub(r'[^a-zA-Z0-9_-]', '_', loop.get("title","loop")[:30])
            key = loop.get("key") or "Unknown"
            bpm = loop.get("bpm") or 0
            author = re.sub(r'[^a-zA-Z0-9_-]', '_', loop.get("author","user")[:15])
            if fmt == "mp3":
                url = loop.get("mp3_url")
                if not url:
                    continue
                filename = f"{bpm}bpm_{key}_{author}_{title}.mp3"
                download_items.append((filename, url, False))
            else:
                # For WAV, need to extract wav_url - we can try to get from loop if provided, else fetch detail
                url = loop.get("wav_url")
                if not url:
                    # fetch detail page authenticated to find wav
                    try:
                        sess = auth.authenticated_session()
                        durl = f"{BASE}/loops/detail/{lid}"
                        r = sess.get(durl, headers=HEADERS, timeout=15)
                        wav = extract_wav_url_from_page(r.text, lid)
                        if wav:
                            url = wav
                        else:
                            pre_errors.append((lid, "WAV not found; no MP3 substitute included"))
                            continue
                    except Exception as exc:
                        pre_errors.append((lid, f"WAV lookup failed: {exc}"))
                        continue
                filename = f"{bpm}bpm_{key}_{author}_{title}.wav"
                download_items.append((filename, url, True))
    else:
        # No loops_data, fetch each id
        for lid in ids[:6]:  # safety cap 6
            try:
                # Get detail for metadata + mp3_url
                detail = get_loop_detail(lid, use_auth=auth.is_logged_in())
                # detail contains data maybe, but we need mp3_url - for now fallback to known pattern?
                # Instead, we can fetch loop detail page and parse mp3
                sess = auth.authenticated_session() if auth.is_logged_in() else requests
                r = sess.get(f"{BASE}/loops/detail/{lid}", headers=HEADERS, timeout=15)
                html = r.text
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                # find mp3
                mp3 = None
                el = soup.find(attrs={"data-mp3": True})
                if el:
                    mp3 = el.get("data-mp3")
                else:
                    m = re.search(r'contentUrl["\']\s*:\s*["\']([^"\']+\.mp3)', html)
                    if m: mp3 = m.group(1)
                if fmt == "mp3" and mp3:
                    filename = f"looperman-{lid}.mp3"
                    download_items.append((filename, mp3, False))
                elif fmt == "wav":
                    wav = extract_wav_url_from_page(html, lid)
                    if wav:
                        filename = f"looperman-{lid}.wav"
                        download_items.append((filename, wav, True))
                    else:
                        pre_errors.append((lid, "WAV not found; no MP3 substitute included"))
                elif fmt == "mp3" and not mp3:
                    pre_errors.append((lid, "MP3 preview not found"))
                time.sleep(0.5)  # rate limit
            except Exception as e:
                pre_errors.append((lid, f"resolution error: {e}"))

    if not download_items:
        raise HTTPException(status_code=404, detail="no file found - check the ids, or log in for WAV")

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    # Every media fetch goes through download_media: it follows Looperman's
    # 307 redirect and refuses HTML/plain-text bodies (quota pages).
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for lid, reason in pre_errors:
            zf.writestr(f"ERROR_{lid}.txt", reason)
        sess = auth.authenticated_session() if auth.is_logged_in() or fmt=="wav" else requests.Session()
        for filename, url, is_wav in download_items:
            try:
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.hostname not in {"looperman.com", "www.looperman.com"}:
                    zf.writestr(f"ERROR_{filename}.txt", "refused: source is not HTTPS looperman.com")
                    continue
                try:
                    resp = download_media(url, referer=f"{BASE}/", session=sess, timeout=60)
                except RateLimited as exc:
                    zf.writestr(f"ERROR_LIMIT_{filename}.txt", f"Looperman limit reached: {exc}")
                    continue
                except (NotAudio, LoopermanError) as exc:
                    zf.writestr(f"ERROR_{filename}.txt", f"{exc}\nURL: {url}")
                    continue
                content = resp.content
                resp.close()
                if not content:
                    zf.writestr(f"ERROR_{filename}.txt", "empty response from Looperman")
                    continue
                # Sanitize filename
                safe = re.sub(r'[<>:"/\\|?*]', '_', filename)
                zf.writestr(safe, content)
                # Info file
                time.sleep(1.2 if is_wav else 0.6)
            except Exception as e:
                zf.writestr(f"ERROR_{filename}.txt", f"Error: {e}\nURL: {url}")
        # Add README
        readme = f"""Looperman ZIP Export - {len(download_items)} loops
Format: {fmt.upper()}
Generated by LoopHaven
Source: https://www.looperman.com
Note: loops are royalty-free for your productions, but do not redistribute the files as-is.
"""
        zf.writestr("README.txt", readme)

    zip_buffer.seek(0)
    zip_name = payload.filename or f"looperman_{fmt}_{len(download_items)}loops.zip"
    return StreamingResponse(zip_buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{zip_name}"'})

def _download_info(kind, item_id):
    """What you will actually get, without spending a download from the quota."""
    logged_in = auth.is_logged_in()
    detail = (get_loop_detail if kind == "loops" else get_acapella_detail)(item_id, use_auth=logged_in)
    item = detail.get("item") or {}
    expected = "wav" if kind == "loops" else "mp3"
    return {
        "id": str(item_id),
        "kind": "loop" if kind == "loops" else "acapella",
        "logged_in": logged_in,
        "requires_login": True,
        "download_available": bool(logged_in and (detail.get("download_link_present") or item)),
        "expected_format": expected,
        "duration_seconds": item.get("duration_seconds"),
        "title": item.get("title"),
        "author": item.get("author"),
        "bpm": item.get("bpm"),
        "key": item.get("key"),
        "size_hint": item.get("size"),
        "license": item.get("license"),
        "message": (
            f"Ready: GET /api/download/{'wav' if kind == 'loops' else 'audio/acapella'}/{item_id} "
            f"will return a {expected.upper()}."
            if logged_in else "Looperman session required (POST /api/auth/login)."
        ),
    }


@app.get("/api/download/wav-info/{loop_id}")
def wav_info(loop_id: str):
    if not re.fullmatch(r"\d+", loop_id):
        raise HTTPException(status_code=422, detail="loop_id must be numeric")
    return _download_info("loops", loop_id)


@app.get("/api/download/info/{kind}/{item_id}")
def download_info(kind: str, item_id: str):
    if kind not in {"loop", "loops", "acapella", "acapellas"}:
        raise HTTPException(status_code=422, detail="kind must be loop or acapella")
    if not re.fullmatch(r"\d+", item_id):
        raise HTTPException(status_code=422, detail="item_id must be numeric")
    return _download_info("acapellas" if kind.startswith("acap") else "loops", item_id)
