# Contributing to LoopHaven

Thanks for showing up. This project is small, so a focused PR or a good bug
report moves it a lot.

## Ground rules

By participating you agree to keep the project usable and lawful:

- **No audio in the repo.** No `.mp3`, `.wav`, `.zip` of samples, no fixtures
  containing real audio. Redact or synthesise.
- **No credentials.** No `.env`, no session dumps, no logs containing cookies.
- **No quota evasion.** PRs that parallelise downloads, rotate accounts, or
  work around `429` will be closed. That includes "just retry faster".
- **No mass-copy features.** Whole-catalogue dumps, mirrors and republishing
  pipelines are out of scope.

## Get set up

```bash
git clone https://github.com/mohamed-amine-ben-mallessa/loop-haven.git
cd loop-haven
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev,mcp]"
python -m pytest tests/unit -q
```

The unit tests run offline: they feed saved HTML fixtures to the parser and
assert on the URL builders. If you touch parsing, add a fixture — that is the
single most valuable contribution right now.

## Where things live

```
src/loophaven/api/app.py                  FastAPI routes
src/loophaven/cli.py                      the `haven` command
src/loophaven/mcp_server.py               optional MCP tools
src/loophaven/providers/looperman/
  filters.py                              the site's filter vocabulary + resolvers
  scraper.py                              URL builders, parsing, downloads
  auth.py                                 session persistence, login, verification
tests/unit/test_api_scraper.py            offline tests
docs/                                     API, filters, reverse-engineering notes
web/                                      brand assets + local UI prototype
```

Two invariants worth knowing before you edit:

1. **Filters come from the form, not from guessing.** `filters.py` mirrors
   `POST /ajax/ajax_adv_search_modal`. If a value is wrong, fix it there and add
   a test — do not special-case it in a route.
2. **Never infer "logged in" from page markup.** Anonymous pages still contain
   the logout link. `auth._verify_session()` checks that `/account/` is *not*
   redirected to `/account/login`; keep that behaviour.

## Good first issues

- Translate `web/prototype/index.html` (French) or replace it with a minimal
  English page.
- Add parser fixtures: pages with 25 cards, a page with a single result, an
  acapella page without a key, a quota page returned instead of audio.
- Document one more reverse-engineered endpoint from the site's JS bundles.

## Pull requests

- One topic per PR, and say **why** in the description, not just what.
- Run `python -m pytest tests/unit -q` before pushing; CI runs it on 3.10–3.13.
- Match the surrounding style. No formatter is enforced, but keep lines and
  naming consistent with the file you edit.
- If your change alters a response shape, update `docs/API.md` in the same PR.

## Reporting bugs

Include: the route or command, the parameters, the expected result, what you
got, and the traceback. If a page fails to parse, paste the **structure** of the
relevant HTML (tags and classes) — not a full dump with user data.

Never paste cookies, `LOOPERMAN_EMAIL`, `LOOPERMAN_PASSWORD`, or your session
file into an issue.
