# Reverse-engineering Looperman

Looperman has no public API. LoopHaven is built on what the site itself does in
a browser: HTML pages, JSON-LD blocks, a few AJAX endpoints and the advanced
search form. This document records what was measured, so that when the site
changes, the next person knows where to look instead of guessing.

Everything below was observed on the live site. Nothing here is official.

---

## 1. The session contract

A Looperman session is two cookies:

| Cookie | Role |
|---|---|
| `loop_session` | the session itself |
| `loop_csrfc` | CSRF token, mirrored in the page as `csrfToken` |

The token is 32 characters and readable from **any** page:

```python
re.search(r"""(?:var|let|const)\s+csrfToken\s*=\s*['"]([^'"]+)""", html)
```

Every `POST /ajax/...` call needs three things, not one:

```
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
Referer: https://www.looperman.com/loops      # the page you are "on"
```

Omit `X-Requested-With` and the endpoint answers with HTML or a redirect
instead of JSON. Forget the `Referer` and it may reject the request outright.

Login itself is **not** an AJAX call — it is the plain HTML form:

```
POST https://www.looperman.com/account/login
fields: csrftoken, page_token, user_email, upass, user_remember_code=1,
        user_disclaimer=1, submit=submit
```

### The trap that cost the most time

Checking "am I logged in?" by looking for `/account/logout` in the page **does
not work**. That link is present in the markup for anonymous visitors too. The
result was an API reporting `logged_in: true` while every download failed with
"no download link on the page".

What does work: request `/account/` and see whether you are redirected.

```
anonymous  -> GET /account/  -> 302 -> /account/login
logged in  -> GET /account/  -> 200, page contains /users/profile/<your id>
```

Corollary: never infer state from "some `/users/profile/<id>` link exists".
Listing pages link to all of their authors. The only trustworthy id is the one
on `/account/`.

---

## 2. The filter vocabulary comes from a form, not from URLs

The old-style paths (`/loops/genres/<slug>`, `/loops/cats/<slug>`,
`/loops/tags/<slug>`) still exist, but they are thin wrappers. The authoritative
vocabulary is inside the advanced search modal:

```
POST /ajax/ajax_adv_search_modal
  item_type=loops|acapellas|software|tracks
  query_filter_params=<base64 of the current filter array>
  csrftoken=<32 chars>
```

The response is `{title, icon, content}` where `content` is the HTML of the
form: every genre, category and key with its numeric id. That is where
`gid=54` (Trap), `cid=21` (Piano) and `mkey=fsm` (F#m) come from — see
[FILTERS.md](FILTERS.md) for the complete tables.

A concrete search is then a normal GET on the listing page:

```
https://www.looperman.com/loops?gid=54&ftempo=140&ttempo=140&order=date&dir=d
```

Useful consequences:

- **Tempo is a range, not a value.** An exact BPM is `ftempo=140&ttempo=140`.
  Sending only `bpm` is a LoopHaven convenience that fills both bounds.
- **Accidentals are spelled oddly upstream.** `F#m` is `fsm`, `C#m` is `csm`,
  and flats are folded: `Bb` maps to `am`. Accepting the human spelling and
  translating it is LoopHaven's job.
- **`did` (DAW) is not a filter.** It appears on cards, it is ignored by the
  search. LoopHaven exposes it as a card field only. Filtering on it returns
  unrelated results, which is a subtle way to ship a broken feature.
- **`who` (followed users) does filter.** On an account that follows nobody,
  `who=1` returns 0 results where the same search without it returns 5 — the
  filter working, not an ignored parameter. `who=2` returned the identical set
  because nothing was ignored. Numbers and caveats in §6.

---

## 3. Parsing a listing page

Two problems make naive parsing fail.

### Every card shares one container

All ~25 result cards live inside a **single** `div.col-12`. So this:

```python
soup.select_one("div.col-12").find_all(...)   # wrong
```

returns the same ancestor for every card, and pairing metadata with the right
item silently slides by one. The reliable segmentation is by player markers:
each item has exactly one `[data-mp3]` attribute, in document order.

LoopHaven splits the document into `[start, next_start)` ranges around those
markers, then reads each field **inside its own range**. That is why a card's
BPM, key and preview can never come from the neighbouring card.

### The counters lie in two different ways

The result window is printed only on page 1:

```
Loops 1 - 25 of 5,000
```

Small result sets instead print `Showing 4 ... loops`. Pages ≥ 2 print neither.
And the total is **capped at 5,000** no matter how many results really exist.

LoopHaven therefore returns:

```json
"pagination": { "from": 1, "to": 25, "per_page": 25, "total": 5000,
                "total_pages": null, "total_capped": true }
```

`total: null` past page 1 is deliberate. Inventing a number would be worse than
admitting there is none.

---

## 4. Detail pages and the real download link

A detail page (`/loops/detail/<id>/<slug>`) carries:

- a JSON-LD `AudioObject` with title, duration, licence, description, keywords
  and the public preview URL (`contentUrl`);
- the item's own `/getfiles/...` link, **among many others**: the page also
  lists recommended loops, each with its own link. On the page tested, 16
  `/getfiles` links were present and only one belonged to the item.

Taking "the first `/getfiles` on the page" is wrong for the same reason as the
card problem. The correct scope is the one **after the `<h1>`** of the item,
which is what `_main_download_link()` does.

### The download itself

`/getfiles/...` answers with a `307` redirect to a storage URL, then streams the
file. Two failure modes must be distinguished from success:

| What comes back | Meaning |
|---|---|
| `audio/wav`, `audio/mpeg` | the file |
| `text/html` | a quota page or a login page, **not** audio |
| `429` | daily limit reached — wait, do not retry |

LoopHaven validates `Content-Type` and, for loops, the `RIFF…WAVE` header before
calling something a WAV. Early on, a quota page was saved as a 5-second `.wav`
and it took a while to notice — hence the paranoia.

Quotas are **per item and per day**. A `429` is surfaced as `429`, never
smoothed over.

---

## 5. AJAX endpoints observed

Measured from `assets-v3/js/ap-v3.min.js`, `ap-player.min.js` and the pages
themselves. "Used" means LoopHaven relies on it today.

| Endpoint | Parameters | Used | Purpose |
|---|---|---|---|
| `POST /ajax/ajax_adv_search_modal` | `item_type`, `query_filter_params`, `csrftoken` | ✅ | the filter vocabulary |
| `POST /ajax/ajax_favs_modal` | `item_hash`, `item_type` | ✅ | favourite state |
| `POST /ajax/ajax_downloads_modal` | `item_hash`, `item_type` | ❌ | download counters |
| `POST /ajax/ajax_track_plays` | `item_hash`, `item_type` | ❌ | play counts |
| `POST /ajax/modal_player_info` | `url`, `item_type` | ❌ | embedded player config |
| `POST /ajax/userinfo` | `uid` | ❌ | profile popover |
| `POST /ajax/comment_add` | `item_hash`, `item_type`, `content`, `csrftoken` | ❌ | comments |
| `POST /ajax/report_item` | `item_hash`, `item_type`, `reason`, `notes`, `csrftoken` | ❌ | reporting |

`item_hash` is the `data-hash` attribute on a card, not the numeric id. It is
required by the favourite/download endpoints; a detail page contains ~64
occurrences and the first may be empty, so take it from the item's own region.

The unimplemented ones are deliberate: they mutate someone's account or write
public content. LoopHaven reads and downloads; it does not comment, report, or
farm plays.

---

## 6. What is still unknown

- The exact rate-limit window for downloads (observed: daily, per item).
- How the advanced-search token behaves after long idle periods.

If you measure one of these, a PR to this file is as valuable as a code PR.

### Measured on 16 November 2026

Two items that used to be listed here are settled. Both were checked against a
real logged-in account, and the raw numbers are below so they can be re-run
rather than trusted.

**`who=1|2` does filter.** The same search with and without the parameter, on
an account that follows nobody:

| Request | `count` |
|---|---|
| `/api/search?limit=5` | 5 (total 5,000) |
| `/api/search?who=1&limit=5` | **0** |
| `/api/search?who=1&limit=5&order=downloads` | **0** |
| `/api/search?who=2&limit=5` | 5 |

`who=1` is "followed only", so an account that follows nobody gets nothing —
that is the filter doing its job, not an ignored parameter. `who=2` is "remove
ignored"; it returned the identical id list because the account ignores nobody
either, so it is consistent but not independently proven to filter. If you want
to finish that half, ignore a loop and re-run the same comparison.

**Acapellas are always MP3.** Three items reported `expected_format: "mp3"`
from `/api/download/info/acapella/{id}`, and two of them were downloaded and
inspected:

| id | `Content-Type` | `X-Audio-Format` | first bytes |
|---|---|---|---|
| 24926 | `audio/mpeg` | `mp3` | `ID3` |
| 24860 | `audio/mpeg` | `mp3` | `ID3` |

No WAV was observed for an acapella, whatever the request asks for. The
filename in `Content-Disposition` also ends in `.mp3`
(`looperman-a-8294181-0024926-library-of-the-mind.mp3`).

