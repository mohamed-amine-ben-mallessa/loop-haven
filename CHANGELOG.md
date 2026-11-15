# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions use semver.

## [0.1.0] — 2026-11-16

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
