# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions use semver.

## [0.1.1] - 2026-11-16

Metadata and documentation release; the API is unchanged from 0.1.0.

### Added
- Local rate limiter on page reads: 30 per 60 s per process, overridable with
  `LOOPHAVEN_RATE_LIMIT`. A retry loop inside one install looks like abuse from
  the outside, and a ban takes the account's WAV downloads with it. Cached reads
  are free, the counter is exposed on `/api/health`, and an exhausted budget
  answers `429` instead of a `500`.
- Documentation site at <https://mohamed-amine-ben-mallessa.github.io/loop-haven/>:
  one page per question, hand-written HTML with no JavaScript, linked from the
  README and registered as the package's `Documentation` URL.
- `Changelog` project URL, and classifiers/keywords that describe what the
  package is (`Environment :: Web Environment`, `Intended Audience :: Developers`,
  `Topic :: Software Development :: Libraries :: Python Modules`).

### Fixed
- `GET /api/acapellas/search?category=` now returns `422`. Looperman ignores
  `cid=` on that listing and still returns results, so the filter used to look
  like it worked while returning an unfiltered page. The documentation already
  claimed the rejection; the code now does it.
- `username` was `"My Profile"` for every account: the name was read from the
  `/account/` navigation links, which are all labelled "My Profile". It is now
  the page heading (or the first part of the page title).
- `POST /api/download/zip` wrote a French message into its error entries
  (`Limite Looperman atteinte`) in an otherwise English output.
- The README printed the skill-file pointer twice.

## [0.1.0] - 2026-11-16

First public release.

### Added
- FastAPI server exposing search, detail, download, preview streaming, ZIP and
  session routes for loops and acapellas.
- Filter vocabulary reversed from Looperman's own advanced-search form:
  69 genres, 40 categories, 24 keys, 4 time signatures, 10 sort orders, plus the
  acapella vocabularies (usage rights, vocal gender, style, type, autotune).
- Tolerant resolvers: labels, numeric ids and slugs are accepted; `F#m`, `Bb`
  and `4/4` are normalised to what the site submits. Unknown values return
  `422` with suggestions.
- `haven` CLI: search, JSON output for agents, preview playback, favourites,
  login/status/logout, personal ZIP of 2–4 loops.
- Optional MCP server (`loophaven-mcp`) with six tools.
- Session persistence across restarts, verified against `/account/` instead of
  looking for a logout link that is present even when logged out.
- Automatic re-login from `.env` when a persisted cookie expires, with one
  retry inside downloads.
- Honest pagination: `total_capped` when Looperman stops counting at 5,000 and
  `total: null` past page 1.
- Offline test suite (27 tests) covering URL builders, parsing, pagination,
  filter resolution, download validation and session verification.

### Known issues
- Browser UI is a French prototype.
- Acapella full-file export depends on the authenticated flow; only the MP3
  that Looperman actually serves is returned.
