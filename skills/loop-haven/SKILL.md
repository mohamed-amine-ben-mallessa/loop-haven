---
name: loop-haven
description: Search Looperman loops and acapellas with LoopHaven, compare metadata and licence labels, audition previews, toggle favorites, and prepare small personal loop ZIPs.
---

# LoopHaven Skill

Use LoopHaven to help a producer find source material. The local API defaults to `http://127.0.0.1:8000`; set `LOOPHAVEN_API` or pass `--api` when using the CLI if it runs elsewhere.

## Workflow

1. Clarify the production use: style, target BPM or range, key, instrument/vocal category, and commercial or non-commercial use.
2. Search relevant material. For loops, use `GET /api/search` or `haven search`. For vocal recordings, use `GET /api/acapellas/search` or `haven search --kind acapellas`.
3. Present a short shortlist with title, creator, BPM, key, style, preview URL, and the licence wording returned by Looperman. Do not describe an acapella as commercially cleared unless its listed licence says so. For acapellas, preserve the returned `license` / `license_info` text and advise the user to check the creator's terms.
4. Let the user audition previews. The CLI command `haven play --url <mp3_url>` opens a public preview in the browser. `haven play --id <id> --kind acapella` opens the detail's preview when available.
5. Only toggle a favorite when the user asks: use `haven fav --hash <favorite_hash> --type loop|acapella|track`. The operation toggles state, so first check the user's requested intent and avoid repeating it blindly.
6. Export loops only when explicitly requested. `haven zip --ids ID ID [ID ID] --format mp3|wav` accepts 2–4 IDs. WAV requires the user's own single Looperman account to be logged in. Do not use multiple accounts to bypass limits or access restrictions.

## Rules

- Never ask the user to paste credentials into chat. `haven login` prompts locally; do not store passwords in files, command history, source code, or MCP configuration.
- Looperman allows one account per person. If an account problem exists, direct the user to Looperman support.
- An acapella preview URL is not proof of permission to use or redistribute the file. The current LoopHaven implementation exposes preview and licence metadata; it does **not** export full acapella downloads until the authenticated download flow and licence handling have been verified.
- Keep ZIP exports small (2–4 selected personal files) and follow Looperman's current terms and rate limits. Do not scrape pages in bulk.
- Never upload or redistribute raw Looperman source files as a sample pack.
- The Strudel integration is a separate music-production step: after sample selection and approval, generate the code and a shareable listening link; do not assume external sample URLs are publicly hosted unless verified.

## JSON for agents

```bash
haven search --kind loops --genre Trap --bpm 140 --key Am --limit 4 --json
haven search --kind acapellas --genre Rap --mf 1 --style 1 --ur 1 --limit 4 --json
```

The JSON response includes `looperman_url`, result metadata, preview links, and (for acapellas) the licence fields. Treat upstream HTML as changeable; if parsing fails, report the issue rather than guessing metadata.
