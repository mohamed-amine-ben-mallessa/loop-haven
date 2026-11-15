# API reference

Base URL: `http://127.0.0.1:8000` — the server is local and single-user.
Interactive OpenAPI: `/docs`, schema: `/openapi.json`.

| Convention | Meaning |
|---|---|
| `422` | a filter value was rejected — the body says why and often suggests valid values |
| `401` | the route needs an open Looperman session |
| `429` | Looperman's quota is exhausted; wait, do not retry |
| `502` | upstream page or file could not be used as expected (HTML instead of audio, markup change) |

Everything is JSON except the download routes, which stream bytes.

---

## Health and vocabulary

### `GET /api/health`

```json
{"status": "ok", "message": "LoopHaven API proxy ready",
 "base": "https://www.looperman.com",
 "auth": {"logged_in": true, "username": "My Profile", "user_id": "8655176"}}
```

`logged_in` is verified against `/account/`, not guessed from cached state. The
email is never returned.

### `GET /api/filters`

The full vocabulary as JSON: `genres`, `categories`, `keys`, `time_signatures`,
`when`, `order`, `dir`, `per_page`, `who`, `acapella`. Each entry is
`{"id": ..., "label": ...}`. See [FILTERS.md](FILTERS.md) for the tables.

### `GET /api/genres`, `GET /api/categories`, `GET /api/keys`

Shortcuts for one vocabulary at a time.

---

## Search

### `GET /api/search` — loops

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `genre` | str | — | label, id or slug |
| `category` | str | — | label, id or slug |
| `key` | str | — | `Am`, `F#m`, `Bb`, or upstream id |
| `bpm` | int | — | exact tempo; expands to `ftempo` + `ttempo` |
| `ftempo`, `ttempo` | int | — | explicit range |
| `keyword` | str | — | `+include -exclude` |
| `tsig` | str | — | `4/4`, `3/4`, `6/8`, `2/4` |
| `when` | str | — | `1` 24 h, `5` 48 h, `2` 7 d, `3` 30 d, `4` 60 d |
| `order` | str | `date` | see FILTERS.md |
| `dir` | str | `d` | `d` descending, `a` ascending |
| `page` | int | `1` | 1-based |
| `ppage` | int | — | upstream page size: 25, 50, 100 |
| `limit` | int | `10` | results returned, 1–50 |
| `mid` | str | — | only this author id |
| `who` | int | — | `1` followed only, `2` remove ignored (unverified) |
| `favs` | bool | `false` | your favourites (needs a session) |

```bash
curl "http://127.0.0.1:8000/api/search?genre=Trap&bpm=140&key=Cm&limit=2"
```

```json
{
  "success": true,
  "query": {"genre": "Trap", "bpm": 140, "ftempo": 140, "ttempo": 140, ...},
  "resolved": {"genre": {"id": 54, "label": "Trap"},
                "key": {"id": "cm", "label": "Cm"}},
  "looperman_url": "https://www.looperman.com/loops?gid=54&ftempo=140&ttempo=140&order=date&dir=d",
  "count": 2,
  "total": 5000,
  "pagination": {"from": 1, "to": 25, "per_page": 25, "total": 5000,
                  "total_pages": null, "total_capped": true},
  "loops": [ ... ],
  "auth": {"logged_in": true, "username": "My Profile", "user_id": "8655176"}
}
```

`total` and `pagination.total` are `null` beyond page 1 (upstream stops
printing the counter). `total_pages` is `null` when the 5,000 cap is hit, which
is almost always.

**A loop object** (28 fields, all of them read from the item's own card):

```json
{
  "id": "436799",
  "kind": "loop",
  "title": "Lil Uzi Vert Arp Type Loop",
  "url": "https://www.looperman.com/loops/detail/436799/...",
  "author": "NiemiroMTS",
  "author_id": "8513679",
  "author_url": "https://www.looperman.com/users/profile/8513679",
  "date": "2026-11-15",
  "bpm": 140,
  "genre": "Trap",
  "category": "Arpeggio",
  "key": "Cm",
  "time_signature": "4/4",
  "size": "2.31 MB",
  "daw": "FL Studio",
  "duration_seconds": 13,
  "duration_iso": "PT13S",
  "license": "https://www.looperman.com/help/terms",
  "usage_info": "...",
  "conditions": "...",
  "description": "...",
  "keywords": ["..."],
  "tags": ["..."],
  "downloads": "1,234",
  "favorites": "12",
  "comments": "0",
  "mp3_url": "https://www.looperman.com/media/loops/...mp3",
  "waveform": "https://www.looperman.com/media/...png",
  "favorite_hash": "a1b2c3..."
}
```

`mp3_url` is a public preview: no login needed. `favorite_hash` is the
`data-hash` used by the favourite endpoint. `daw` is metadata only — it is not
a search filter.

### `GET /api/acapellas/search`

Same shape, with acapella-only filters:

| Parameter | Type | Notes |
|---|---|---|
| `rights` (alias `ur`) | int | `1` commercial allowed, `2` non-commercial only |
| `mf` | int | `1` male, `2` female, `3` both |
| `style` | int | `1` rap, `2` singing, `3` both |
| `vocal_type` | int | `1` hook, `2` verse, `3` full song |
| `autotune` | int | `1` none, `2` used |
| `adult` | str | `y` keep, `n` remove |
| `mydl` | bool | acapellas you already downloaded (needs a session) |

`genre`, `key`, `bpm`/`ftempo`/`ttempo` (40–220), `keyword`, `tsig`, `mid`,
`who`, `when`, `order`, `dir`, `page`, `ppage`, `favs`, `limit` behave as above.
`category` does **not** exist for acapellas and is rejected.

```bash
curl "http://127.0.0.1:8000/api/acapellas/search?genre=Boom%20Bap&bpm=86&mf=1&style=1&ur=1&limit=2"
```

The response uses `acapellas` instead of `loops`, and each item carries the
`license` / `license_info` wording displayed by the site. That text is a
quotation, not legal advice, and not a grant of rights.

---

## Detail

### `GET /api/loop/{id}`

```json
{"id": "436799",
 "url": "https://www.looperman.com/loops/detail/436799/...",
 "data": { "AudioObject JSON-LD": "..." },
 "item": { "the parsed card fields": "..." },
 "download_link_present": true}
```

`download_link_present` is `false` when the page has no `/getfiles` link for
this item — usually an expired session or an exhausted quota.

### `GET /api/acapellas/{id}`

Same envelope for an acapella: JSON-LD, preview, and the usage/licence notice.

---

## Download

### `GET /api/download/info/{kind}/{id}`

Free: it fetches the detail page and tells you what a download would produce,
**without spending quota**.

```json
{"id": "436799", "kind": "loop", "logged_in": true,
 "requires_login": true, "download_available": true,
 "expected_format": "wav", "duration_seconds": 13,
 "title": "Lil Uzi Vert arp type loop", "author": "NiemiroMTS",
 "bpm": 140, "key": "Cm", "size_hint": "2.31 MB",
 "license": "https://www.looperman.com/help/terms"}
```

`kind` is `loop`/`loops` or `acapella`/`acapellas`.

### `GET /api/download/audio/{kind}/{id}`

Streams the item's own file, with the real `Content-Type`, the real filename in
`Content-Disposition`, and `X-Audio-Format` (`wav` for loops, `mp3` for
acapellas). Requires an open session (`401` otherwise).

```
HTTP 200
Content-Type: audio/wav
X-Audio-Format: wav
Content-Disposition: attachment; filename="looperman-l-8513679-0436799-....wav"
```

A `429` is Looperman's quota, passed through unchanged. A `502` means upstream
returned HTML (quota page, login page) instead of audio — never saved as a
file.

### `GET /api/download/wav/{id}` and `/api/download/wav-info/{id}`

Legacy aliases kept for older scripts. Prefer `/api/download/audio/...`.

### `POST /api/download/zip`

A personal pack of 2–4 loops.

```json
{"ids": ["434657", "434373"], "format": "mp3", "filename": "pack.zip"}
```

- `format`: `mp3` (public previews) or `wav` (needs a session).
- `loops`: optional array of search results, reused for filenames and metadata.
- Any file that fails is written into the ZIP as `ERROR_<id>.txt` with the
  reason, instead of substituting a different format silently. A quota failure
  becomes `ERROR_LIMIT_<file>.txt`.
- The ZIP contains a `README.txt` recalling the licence situation.

---

## Session

### `POST /api/auth/login`

```json
{"email": "...", "password": "..."}
```

Opens a Looperman session and persists the cookie jar. The password is used for
the login POST and never stored. Response: `{"success": true, "user_id": "...",
"username": "..."}`.

### `GET /api/auth/status`

```json
{"logged_in": true, "username": "My Profile", "user_id": "8655176"}
```

Re-verified against `/account/`, so an expired cookie reports `false` instead of
a stale `true`.

### `POST /api/auth/logout`

Closes the local session (does not touch Looperman).

### `POST /api/favorites/toggle`

```json
{"item_hash": "a1b2c3...", "item_type": "loop"}
```

Toggles the favourite state — it is not idempotent. Requires a session. Use the
`favorite_hash` returned by a search result.

---

## Media helpers

### `GET /api/stream/preview?url=<looperman media url>`

Streams a public MP3 preview inline, forwarding `Range` for audio players. Only
`https://www.looperman.com/media/loops/...` and `/media/acapellas/...` are
accepted; redirects are refused.

### `GET /api/download/proxy?url=<looperman url>`

Same-origin download proxy for previews. Hostname is validated exactly
(`looperman.com`, `www.looperman.com`), redirects must stay on it, `429` is
passed through, and HTML responses are rejected.
