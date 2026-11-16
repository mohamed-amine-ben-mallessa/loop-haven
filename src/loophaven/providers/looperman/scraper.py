import os
import requests
import re
import time
from collections import deque
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote, urlencode
import json

from . import filters

BASE = "https://www.looperman.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}


class LoopermanError(Exception):
    """Upstream problem worth surfacing to the API layer as a real error."""


class RateLimited(LoopermanError):
    """Looperman refuses the transfer (daily download quota or abuse throttle)."""


class NotAudio(LoopermanError):
    """Looperman answered with HTML/plain text where audio was expected."""


# Listing pages are re-read a lot while a user browses; a short TTL keeps us
# from hammering Looperman (which throttles and blocks IPs) without making the
# search feel stale.
_CACHE = {}
_CACHE_TTL = 90.0
_CACHE_MAX = 64


def _cache_get(key):
    hit = _CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key, value):
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.monotonic(), value)


def clear_cache():
    _CACHE.clear()


# One account, one IP, one browser: 30 page reads a minute is roughly one every
# two seconds, which is faster than a human browsing and slower than the
# patterns Looperman throttles. The counter lives in this process only, so it
# protects a single-user install from its own retry loops, nothing more.
# Raise or lower it with LOOPHAVEN_RATE_LIMIT; a bad value must never make the
# module unimportable, so it falls back to the default.
_RATE_LIMIT_WINDOW = 60.0
_RATE_LIMIT_DEFAULT = 30


def _configured_rate_limit():
    try:
        value = int(os.environ.get("LOOPHAVEN_RATE_LIMIT", "") or _RATE_LIMIT_DEFAULT)
    except (TypeError, ValueError):
        return _RATE_LIMIT_DEFAULT
    return value if value > 0 else _RATE_LIMIT_DEFAULT


_RATE_LIMIT_MAX = _configured_rate_limit()
_rate_timestamps = deque()


def _rate_limit_check():
    """Raise `RateLimited` when this process is over its local budget."""
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW
    while _rate_timestamps and _rate_timestamps[0] < cutoff:
        _rate_timestamps.popleft()
    if len(_rate_timestamps) >= _RATE_LIMIT_MAX:
        # An empty deque is only possible when the budget was set to 0; report a
        # full window rather than crashing on a missing index.
        oldest = _rate_timestamps[0] if _rate_timestamps else now
        retry_after = max(1, round(_RATE_LIMIT_WINDOW - (now - oldest)))
        raise RateLimited(
            f"local rate limit reached ({len(_rate_timestamps)} page reads in "
            f"{_RATE_LIMIT_WINDOW:.0f}s, max {_RATE_LIMIT_MAX}); retry in {retry_after}s. "
            "This is LoopHaven protecting the account from Looperman's own throttling."
        )
    _rate_timestamps.append(now)


def _rate_limit_reset():
    """Forget the recorded page reads (tests, and after a known quiet period)."""
    _rate_timestamps.clear()


def rate_limit_state():
    """Rate-limit counters for `/api/health`. No URLs, no credentials."""
    cutoff = time.monotonic() - _RATE_LIMIT_WINDOW
    recent = sum(1 for stamp in _rate_timestamps if stamp >= cutoff)
    return {
        "max_requests": _RATE_LIMIT_MAX,
        "window_seconds": int(_RATE_LIMIT_WINDOW),
        "recent_requests": recent,
        "remaining": max(0, _RATE_LIMIT_MAX - recent),
    }


def _session(use_auth):
    if use_auth:
        try:
            from . import auth
            if auth.is_logged_in():
                return auth.authenticated_session()
        except Exception:
            pass
    return requests


def fetch_html(url, use_auth=False, timeout=20):
    """GET a Looperman page as text, with a short-lived cache."""
    key = (url, bool(use_auth))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    _rate_limit_check()
    response = _session(use_auth).get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    _cache_put(key, response.text)
    return response.text


def _abs(href):
    """Absolute URL without doubling the host (cards already emit absolute hrefs)."""
    if not href:
        return None
    return urljoin(BASE, href)


def _iso_duration_seconds(value):
    """PT27S / PT1M38S -> seconds."""
    if not value:
        return None
    match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", str(value))
    if not match:
        return None
    hours, minutes, seconds = (float(part) if part else 0 for part in match.groups())
    return int(round(hours * 3600 + minutes * 60 + seconds))


def _card_stat(card, label):
    """Read a badge counter ("12 downloads", "3 favs", "0 comments")."""
    if card is None:
        return None
    for el in card.select("[data-bs-title]"):
        hint = el.get("data-bs-title") or ""
        match = re.fullmatch(rf"(\d[\d,]*)\s*{label}", hint, re.I)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _card_duration(card):
    """Card tooltips carry "27 seconds"; the timer span is a fallback."""
    if card is None:
        return None
    for el in card.select("[data-bs-title]"):
        match = re.fullmatch(r"(\d+)\s+seconds?", el.get("data-bs-title") or "", re.I)
        if match:
            return int(match.group(1))
    timer = card.select_one(".jp-timer")
    if timer:
        match = re.search(r"(\d+):(\d{2})", timer.get_text(" ", strip=True))
        if match:
            return int(match.group(1)) * 60 + int(match.group(2))
    return None


def _parse_tag_wrapper(wrapper):
    """The .tag-wrapper holds bpm/genre/category/tsig/size/key/daw as anchors."""
    data = {"tags": [], "bpm": None, "genre": None, "category": None, "key": None,
            "size": None, "time_signature": None, "daw": None}
    if wrapper is None:
        return data
    for anchor in wrapper.select("a"):
        text = anchor.get_text(" ", strip=True)
        hint = anchor.get("data-bs-title") or ""
        if not text:
            continue
        data["tags"].append({"label": text, "url": _abs(anchor.get("href"))})
        bpm_match = re.match(r"^(\d+)\s*bpm$", text, re.I)
        if bpm_match:
            data["bpm"] = int(bpm_match.group(1))
        elif hint.startswith("Genre :"):
            data["genre"] = re.sub(r"\s+(Loops|Acapellas)$", "", text).strip()
        elif hint.startswith("Category :"):
            data["category"] = re.sub(r"\s+Loops$", "", text).strip()
        elif hint.startswith("Time Signature :"):
            data["time_signature"] = text
        elif hint.startswith("File Size :"):
            data["size"] = text
        elif "key of" in hint.lower():
            key_match = re.search(r"key of\s+(.+)", hint, re.I)
            data["key"] = (key_match.group(1) if key_match else text.replace("Key :", "")).strip()
        elif "created with" in hint.lower():
            daw_match = re.search(r"created with\s+(.+)", hint, re.I)
            data["daw"] = daw_match.group(1).strip() if daw_match else text
    return data


def _page_window(html):
    """Result window + honest total.

    Looperman only prints "Loops 1 - 25 of N" on the first page, and caps N at
    5,000. Small result sets omit that counter but print "Showing 4 ... loops".
    Later pages carry neither, so they report None instead of inventing a total.
    """
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    match = re.search(r"(?:Loops|Acapellas)\s+([\d,]+)\s*-\s*([\d,]+)\s+of\s+([\d,]+)", text)
    if match:
        total = int(match.group(3).replace(",", ""))
        return {"from": int(match.group(1).replace(",", "")),
                "to": int(match.group(2).replace(",", "")),
                "total": total,
                "total_capped": total >= filters.TOTAL_CAP}
    showing = re.search(r"Showing\s+([\d,]+)\s+[^.]{0,80}?(?:loops|acapellas)\b", text, re.I)
    if showing:
        total = int(showing.group(1).replace(",", ""))
        return {"from": 1, "to": total, "total": total,
                "total_capped": total >= filters.TOTAL_CAP}
    return {"from": None, "to": None, "total": None, "total_capped": False}


def _pagination(window, fallback_count):
    """Turn the window into pagination metadata, flagging the 5,000 cap."""
    per_page = (window["to"] - window["from"] + 1) if window["from"] and window["to"] else fallback_count
    total = window.get("total")
    capped = bool(window.get("total_capped"))
    total_pages = None
    if total and per_page and not capped:
        total_pages = (total + per_page - 1) // per_page
    return {
        "from": window["from"],
        "to": window["to"],
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "total_capped": capped,
    }


def _item_regions(soup):
    """Split a page into per-item node ranges, in document order.

    Every card of a listing lives inside ONE shared ``div.col-12``, so "find
    the parent container" returns the same ancestor for all of them — that is
    what made items inherit their predecessor's tags and mp3. Looperman emits
    each item as ``[data-mp3]`` marker -> card/title -> download -> tags, and
    the markers are 1:1 with the items, so they give reliable boundaries.
    Falls back to the title anchors when a page carries no markers.
    """
    nodes = [n for n in soup.descendants if getattr(n, "name", None)]
    index = {id(n): i for i, n in enumerate(nodes)}
    markers = [n for n in nodes if n.has_attr("data-mp3")]
    anchors = markers if markers else soup.select("a.player-title")
    if not anchors:
        return []
    starts = sorted(index[id(a)] for a in anchors)
    regions = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(nodes)
        regions.append(nodes[start:end])
    return regions


def _region_first(region, predicate):
    for node in region:
        if predicate(node):
            return node
    return None


def _iter_items(soup, href_contains=None):
    """Yield the nodes belonging to each item, correctly scoped.

    ``href_contains`` keeps only items whose title points at that kind of
    detail page (``/loops/detail/`` vs ``/acapellas/detail/``).
    """
    for region in _item_regions(soup):
        title = _region_first(
            region,
            lambda n: (n.name == "a" and "player-title" in (n.get("class") or [])
                       and (href_contains is None or href_contains in (n.get("href") or ""))),
        )
        if title is None:
            continue
        yield {
            "region": region,
            "title": title,
            "card": _region_first(region, lambda n: n.name == "div" and "bg-player" in (n.get("class") or [])),
            "tags": _region_first(region, lambda n: "tag-wrapper" in (n.get("class") or [])),
            "mp3": _region_first(region, lambda n: n.has_attr("data-mp3")),
            "hash": _region_first(region, lambda n: n.has_attr("data-hash")),
            "waveform": _region_first(region, lambda n: "player-waveform-image" in (n.get("class") or [])),
            "profile": _region_first(region, lambda n: n.name == "a" and "/users/profile/" in (n.get("href") or "")),
        }


def _main_download_link(html):
    """The download link of the item the page is about (not a related card).

    On a detail page the item's own block is rendered first, right after the
    h1: h1 -> mp3 marker -> title -> /getfiles -> tag-wrapper. Related cards
    follow, so the first /getfiles link after the h1 is the right one.
    """
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1")
    if heading is not None:
        link = heading.find_next("a", href=re.compile(r"/getfiles/"))
        if link is not None:
            return _abs(link.get("href"))
    link = soup.select_one('a[href*="/getfiles/"]')
    return _abs(link.get("href")) if link else None


def download_media(url, referer=None, session=None, timeout=60):
    """Open a /getfiles URL and return the streaming response.

    Looperman answers /getfiles with a 307 to the signed media URL, so
    redirects must be followed; a redirect-less request streams an empty body
    and produces the truncated files this API used to serve. A rate-limited
    account gets a plain-text "Sorry..." body with a 429 instead of audio.
    """
    sess = session or _session(True)
    headers = {**HEADERS, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    response = sess.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
    if response.status_code == 429:
        body = response.raw.read(200, decode_content=True) if hasattr(response, "raw") else b""
        response.close()
        raise RateLimited(
            "Looperman refused the download (daily quota reached or throttled). "
            + body.decode("latin-1", "replace").strip()[:160]
        )
    if response.status_code >= 400:
        response.close()
        raise LoopermanError(f"Looperman answered HTTP {response.status_code}")
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type.startswith("text/") or content_type == "application/json":
        body = b""
        try:
            for chunk in response.iter_content(256):
                body += chunk
                if len(body) >= 200:
                    break
        finally:
            response.close()
        raise NotAudio(
            f"Looperman returned {content_type or 'an unknown type'} instead of an audio file: "
            + body.decode("latin-1", "replace").strip()[:160]
        )
    return response


def media_filename(response, fallback):
    disposition = response.headers.get("content-disposition") or ""
    match = re.search(r'filename\*?=(?:UTF-8\x27\x27)?["\']?([^"\';]+)', disposition)
    if match:
        return match.group(1).strip()
    return fallback


def extract_download_link(html, item_id=None):
    """Public name for the h1-scoped /getfiles lookup (used by the ZIP export)."""
    return _main_download_link(html)

def _bpm_pairs(ftempo, ttempo):
    """ftempo/ttempo are a real range; a single bpm means "exactly"."""
    if ftempo is None and ttempo is None:
        return []
    low = ftempo if ftempo is not None else ttempo
    high = ttempo if ttempo is not None else ftempo
    return [("ftempo", low), ("ttempo", high)]


def _common_pairs(key=None, ftempo=None, ttempo=None, keyword=None, tsig=None,
                  mid=None, when=None, order=None, direction=None, who=None,
                  ppage=None, page=None):
    """Filters shared by loops and acapellas, resolved to Looperman's own ids."""
    pairs = []
    mkey, _ = filters.resolve_key(key)
    if mkey:
        pairs.append(("mkey", mkey))
    pairs.extend(_bpm_pairs(ftempo, ttempo))
    tsig_value, _ = filters.resolve_time_signature(tsig)
    if tsig_value:
        pairs.append(("tsig", tsig_value))
    if mid:
        pairs.append(("mid", mid))
    if keyword:
        # urlencode below turns a leading '+' into %2B, which is what
        # Looperman's +include / -exclude syntax needs.
        pairs.append(("keys", keyword))
    when_value, _ = filters.resolve_choice("when", when, filters.WHEN)
    if when_value:
        pairs.append(("when", when_value))
    if order:
        if order not in filters.ORDERS:
            raise filters.UnknownFilter("order", order, list(filters.ORDERS))
        pairs.append(("order", order))
        pairs.append(("dir", "a" if direction == "a" else "d"))
    who_value, _ = filters.resolve_choice("who", who, filters.WHO)
    if who_value:
        pairs.append(("who", who_value))
    if ppage:
        if int(ppage) not in filters.PER_PAGE.values():
            raise filters.UnknownFilter("ppage", ppage, ["25", "50", "100"])
        pairs.append(("ppage", int(ppage)))
    if page and int(page) > 1:
        pairs.append(("page", int(page)))
    return pairs


def build_search_url(genre=None, category=None, key=None, ftempo=None, ttempo=None,
                     keyword=None, order="date", direction="d", page=1, when=None,
                     tsig=None, mid=None, who=None, ppage=None, favs=False):
    """Loop listing URL built from the ids Looperman's own form submits.

    Everything lives on /loops: the older /loops/genres/<slug> and
    /loops/tags/<slug> routes were guesses, and a wrong slug silently returns
    an empty page instead of an error.
    """
    pairs = []
    gid, _ = filters.resolve_genre(genre)
    if gid:
        pairs.append(("gid", gid))
    cid, _ = filters.resolve_category(category)
    if cid:
        pairs.append(("cid", cid))
    pairs.extend(_common_pairs(key=key, ftempo=ftempo, ttempo=ttempo, keyword=keyword,
                               tsig=tsig, mid=mid, when=when, order=order,
                               direction=direction, who=who, ppage=ppage, page=page))
    if favs:
        pairs.append(("favs", 1))
    return f"{BASE}/loops" + (f"?{urlencode(pairs)}" if pairs else "")


def build_acapella_search_url(genre=None, key=None, ftempo=None, ttempo=None, keyword=None,
                              tsig=None, mid=None, ur=None, autotune=None, mf=None,
                              style=None, vocal_type=None, adult=None, when=None,
                              who=None, order="date", direction="d", page=1, ppage=None,
                              favs=False, mydl=False):
    """Acapella listing URL. Acapellas have gid but no category, plus their own filters."""
    pairs = []
    gid, _ = filters.resolve_genre(genre)
    if gid:
        pairs.append(("gid", gid))
    pairs.extend(_common_pairs(key=key, ftempo=ftempo, ttempo=ttempo, keyword=keyword,
                               tsig=tsig, mid=mid, when=when, order=order,
                               direction=direction, who=who, ppage=ppage, page=page))
    rights, _ = filters.resolve_choice("rights", ur, filters.USAGE_RIGHTS)
    if rights:
        pairs.append(("ur", rights))
    gender, _ = filters.resolve_choice("genders", mf, filters.VOCAL_GENDERS)
    if gender:
        pairs.append(("mf", gender))
    style_value, _ = filters.resolve_choice("style", style, filters.VOCAL_STYLES)
    if style_value:
        pairs.append(("style", style_value))
    type_value, _ = filters.resolve_choice("type", vocal_type, filters.VOCAL_TYPES)
    if type_value:
        pairs.append(("type", type_value))
    autotune_value, _ = filters.resolve_choice("autotune", autotune, filters.AUTOTUNE)
    if autotune_value:
        pairs.append(("autotune", autotune_value))
    adult_value, _ = filters.resolve_choice("adult", adult, filters.ADULT)
    if adult_value:
        pairs.append(("adult", adult_value))
    if favs:
        pairs.append(("favs", 1))
    if mydl:
        pairs.append(("mydl", 1))
    return f"{BASE}/acapellas" + (f"?{urlencode(pairs)}" if pairs else "")


def scrape_acapellas(url, limit=4, use_auth=False):
    """Parse acapella listing cards and expose their public preview URLs and licence labels."""
    try:
        html = fetch_html(url, use_auth=use_auth, timeout=20)
    except RateLimited:
        raise
    except Exception as exc:
        return {"error": str(exc), "url": url, "acapellas": [], "count": 0}

    soup = BeautifulSoup(html, "lxml")
    items = []
    for item in _iter_items(soup, href_contains="/acapellas/detail/"):
        title_el = item["title"]
        card = item["card"]
        href = title_el.get("href") or ""
        match = re.search(r"/acapellas/detail/(\d+)(?:/([^?#]+))?", href)
        if not match:
            continue
        item_id = match.group(1)

        tag_wrapper = item["tags"]
        mp3_url = item["mp3"].get("data-mp3") if item["mp3"] is not None else None
        favorite_hash = item["hash"].get("data-hash") if item["hash"] is not None else None

        author, author_id, author_url = None, None, None
        profile = item["profile"]
        if profile is not None:
            author = profile.get_text(" ", strip=True) or None
            if not author:
                avatar = profile.find("img")
                author = avatar.get("alt") if avatar else None
            author_url = _abs(profile.get("href"))
            author_match = re.search(r"/users/profile/(\d+)", profile.get("href") or "")
            author_id = author_match.group(1) if author_match else None

        waveform = item["waveform"].get("src") if item["waveform"] is not None else None

        tags = _parse_tag_wrapper(tag_wrapper)
        genre_name = tags["genre"] or None
        key_name = tags["key"]
        time_signature = tags["time_signature"]
        file_size = tags["size"]
        gender = None
        vocal_style = None
        vocal_type = None
        license_label = None
        has_lyrics = False
        autotune = False
        if tag_wrapper is not None:
            for anchor in tag_wrapper.select("a"):
                text = anchor.get_text(" ", strip=True)
                hint = anchor.get("data-bs-title", "")
                if "contains Male vocals" in hint:
                    gender = "male"
                elif "contains Female vocals" in hint:
                    gender = "female"
                elif "vocal style" in hint.lower():
                    vocal_style = text
                elif re.search(r"Type\s*:", hint, re.I):
                    vocal_type = text
                elif "set this acapella as" in hint.lower() or "usage :" in hint.lower():
                    license_label = text
                elif "lyrics" in hint.lower() and ("supplied" in hint.lower() or "contains" in hint.lower()):
                    has_lyrics = True
                elif "recorded using autotune" in hint.lower():
                    autotune = True

        items.append({
            "id": item_id,
            "title": title_el.get_text(" ", strip=True),
            "url": _abs(href),
            "author": author,
            "author_id": author_id,
            "author_url": author_url,
            "date": None,
            "bpm": tags["bpm"],
            "genre": genre_name,
            "key": key_name,
            "time_signature": time_signature,
            "size": file_size,
            "duration_seconds": _card_duration(card),
            "downloads": _card_stat(card, "downloads"),
            "favorites": _card_stat(card, "favs"),
            "comments": _card_stat(card, "comments"),
            "tags": tags["tags"],
            "gender": gender,
            "style": vocal_style,
            "type": vocal_type,
            "license": license_label,
            "has_lyrics": has_lyrics,
            "autotune": autotune,
            "mp3_url": mp3_url,
            "waveform": waveform,
            "favorite_hash": favorite_hash,
        })
        if len(items) >= limit:
            break

    window = _page_window(html)
    return {"url": url, "count": len(items), "acapellas": items,
            "total_found": window["total"],
            "page": _pagination(window, len(items))}


def scrape_loops(url, limit=4, use_auth=False):
    try:
        html = fetch_html(url, use_auth=use_auth, timeout=20)
    except RateLimited:
        raise
    except Exception as exc:
        return {"error": str(exc), "url": url, "loops": []}

    soup = BeautifulSoup(html, "lxml")
    loops = []
    for item in _iter_items(soup, href_contains="/loops/detail/"):
        title_el = item["title"]
        card = item["card"]
        href = title_el.get("href") or ""
        match = re.search(r"/loops/detail/(\d+)(?:/([^?#]+))?", href)
        if not match:
            continue
        loop_id = match.group(1)
        slug = (match.group(2) or "").strip("/")

        tags = _parse_tag_wrapper(item["tags"])

        author, author_id, author_url = "Unknown", None, None
        profile = item["profile"]
        if profile is not None:
            author = profile.get_text(" ", strip=True) or None
            if not author:
                avatar = profile.find("img")
                author = avatar.get("alt") if avatar else None
            author = author or "Unknown"
            author_url = _abs(profile.get("href"))
            author_match = re.search(r"/users/profile/(\d+)", profile.get("href") or "")
            author_id = author_match.group(1) if author_match else None

        mp3_url = item["mp3"].get("data-mp3") if item["mp3"] is not None else None
        waveform = item["waveform"].get("src") if item["waveform"] is not None else None
        if waveform is None and mp3_url:
            waveform = mp3_url.replace(".mp3", ".png")

        favorite_hash = item["hash"].get("data-hash") if item["hash"] is not None else None

        date_match = re.search(r"\d{1,2}(?:st|nd|rd|th)\s+\w+\s+\d{4}\s+\d{1,2}:\d{2}",
                               card.get_text(" ", strip=True) if card is not None else "")

        genre = tags["genre"]
        if not genre:
            heading = soup.find("h1")
            if heading:
                genre_match = re.search(r"Free(?:\s+\d+\s*Bpm)?\s+(.+?)\s+Loops",
                                        heading.get_text(" ", strip=True), re.I)
                genre = genre_match.group(1).strip() if genre_match else None

        duration_seconds = _card_duration(card)
        loops.append({
            "id": loop_id,
            "title": title_el.get_text(" ", strip=True),
            "url": _abs(href),
            "author": author,
            "author_id": author_id,
            "author_url": author_url,
            "date": date_match.group(0) if date_match else None,
            "bpm": tags["bpm"],
            "genre": genre,
            "category": tags["category"],
            "key": tags["key"] or "Unknown",
            "time_signature": tags["time_signature"],
            "size": tags["size"],
            "daw": tags["daw"],
            "duration_seconds": duration_seconds,
            "downloads": _card_stat(card, "downloads"),
            "favorites": _card_stat(card, "favs"),
            "comments": _card_stat(card, "comments"),
            "tags": tags["tags"],
            "mp3_url": mp3_url,
            "waveform": waveform,
            "description": None,
            "favorite_hash": favorite_hash,
        })
        if len(loops) >= limit:
            break

    if not loops:
        # Last-resort markup: plain detail links with no player card.
        seen = set()
        for link in soup.find_all("a", href=re.compile(r"/loops/detail/\d+/")):
            href = link.get("href") or ""
            match = re.search(r"/loops/detail/(\d+)(?:/([^?#]+))?", href)
            if not match or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 3:
                continue
            wrapper = link.find_next("div", class_="tag-wrapper")
            tags = _parse_tag_wrapper(wrapper)
            mp3_el = link.find_next(attrs={"data-mp3": True})
            mp3_url = mp3_el.get("data-mp3") if mp3_el else None
            loops.append({
                "id": match.group(1), "title": title, "url": _abs(href), "author": "Unknown",
                "author_id": None, "author_url": None, "date": None,
                "bpm": tags["bpm"], "genre": tags["genre"], "category": tags["category"],
                "key": tags["key"] or "Unknown", "time_signature": tags["time_signature"],
                "size": tags["size"], "daw": tags["daw"], "duration_seconds": None,
                "downloads": None, "favorites": None, "comments": None, "tags": tags["tags"],
                "mp3_url": mp3_url, "waveform": (mp3_url or "").replace(".mp3", ".png") or None,
                "description": None, "favorite_hash": None,
            })
            if len(loops) >= limit:
                break

    window = _page_window(html)
    return {
        "url": url,
        "count": len(loops),
        "loops": loops,
        "total_found": window["total"] if window["total"] is not None else len(loops),
        "page": _pagination(window, len(loops)),
    }

def _jsonld_audio(html):
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        types = data.get("@type") or []
        if isinstance(types, str):
            types = [types]
        if "AudioObject" in types:
            return data
    return None


def _normalize_detail(data, html, kind, item_id, url):
    """Merge JSON-LD with the item's main card so detail matches search results."""
    soup = BeautifulSoup(html, "lxml")
    creator = data.get("creator") or {}
    artist = data.get("byArtist") or {}
    wrapper = soup.select_one(".tag-wrapper")
    tags = _parse_tag_wrapper(wrapper)
    card = soup.select_one("div.bg-player")
    author_url = _abs(creator.get("url"))
    author_id = None
    if author_url:
        match = re.search(r"/users/profile/(\d+)", author_url)
        author_id = match.group(1) if match else None
    return {
        "id": str(item_id),
        "kind": kind,
        "title": data.get("name"),
        "url": data.get("url") or url,
        "author": artist.get("name") or creator.get("name"),
        "author_id": author_id,
        "author_url": author_url,
        "date": data.get("datePublished"),
        "bpm": tags["bpm"],
        "genre": data.get("genre") or tags["genre"],
        "category": tags["category"],
        "key": tags["key"],
        "time_signature": tags["time_signature"],
        "size": tags["size"],
        "daw": tags["daw"],
        "duration_seconds": _iso_duration_seconds(data.get("duration")),
        "duration_iso": data.get("duration"),
        "license": data.get("license"),
        "usage_info": data.get("usageInfo"),
        "conditions": data.get("conditionsOfAccess"),
        "description": data.get("description"),
        "keywords": data.get("keywords"),
        "tags": tags["tags"],
        "downloads": _card_stat(card, "downloads"),
        "favorites": _card_stat(card, "favs"),
        "comments": _card_stat(card, "comments"),
        "mp3_url": data.get("contentUrl"),
        "waveform": data.get("thumbnailUrl"),
    }


def resolve_download(kind, item_id, use_auth=True):
    """Return (media_url, referer) for an item's own download link.

    The /getfiles href only exists in the logged-in HTML, and a detail page
    carries up to 15 links for the "you might also like" cards, so the link is
    taken from the block that belongs to the page's own h1.
    """
    collection = "acapellas" if str(kind).startswith("acap") else "loops"
    page_url = f"{BASE}/{collection}/detail/{item_id}"
    html = fetch_html(page_url, use_auth=use_auth, timeout=20)
    link = _main_download_link(html)
    if not link and use_auth:
        # A persisted cookie can expire while the service runs; /api/health
        # then keeps reporting the last known state. Re-login once and retry
        # instead of telling the user their session is fine but downloads fail.
        from . import auth as _auth
        if _auth.relogin():
            html = fetch_html(page_url, use_auth=True, timeout=20)
            link = _main_download_link(html)
    if not link:
        raise LoopermanError(
            "No download link on the page: session not logged in, quota reached, "
            "or Looperman markup changed."
        )
    return link, page_url


def get_acapella_detail(acapella_id, use_auth=False):
    url = f"{BASE}/acapellas/detail/{acapella_id}"
    try:
        html = fetch_html(url, use_auth=use_auth, timeout=20)
    except Exception as exc:
        return {"id": str(acapella_id), "error": str(exc)}
    data = _jsonld_audio(html)
    if not data:
        return {"id": str(acapella_id), "url": url, "error": "AudioObject JSON-LD absent"}
    return {"id": str(acapella_id), "data": data, "url": url,
            "mp3_url": data.get("contentUrl"),
            "license_info": data.get("conditionsOfAccess"),
            "download_link_present": _main_download_link(html) is not None,
            "item": _normalize_detail(data, html, "acapella", acapella_id, url)}


def get_loop_detail(loop_id, use_auth=False):
    url = f"{BASE}/loops/detail/{loop_id}"
    try:
        html = fetch_html(url, use_auth=use_auth, timeout=20)
    except Exception as exc:
        return {"id": str(loop_id), "error": str(exc)}
    data = _jsonld_audio(html)
    if not data:
        return {"id": str(loop_id), "url": url, "error": "AudioObject JSON-LD absent"}
    return {"id": str(loop_id), "data": data, "url": url,
            "item": _normalize_detail(data, html, "loop", loop_id, url),
            "download_link_present": _main_download_link(html) is not None}
