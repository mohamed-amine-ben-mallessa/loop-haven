# Security

## The API has no authentication

LoopHaven is a **local, single-user** tool. The FastAPI server binds to
`127.0.0.1` in every documented command, and it trusts whoever can reach it:
that is why `/api/auth/login`, `/api/download/*` and the session cookie are
usable without a token.

**Do not expose it to a network or the internet as-is.** If you need that, put
it behind a reverse proxy with authentication and TLS, and treat every route as
privileged.

## Credentials

- `LOOPERMAN_EMAIL` / `LOOPERMAN_PASSWORD` are read from the environment or a
  local `.env` file. They are never written to logs and never returned by any
  route (`/api/health` strips the email).
- The session cookie jar lives outside the repo
  (`%APPDATA%\loophaven\session.json`, or `LOOPHAVEN_SESSION_FILE`) and is
  created with owner-only permissions where the OS supports it.
- Nothing is sent anywhere except to `looperman.com`.

If you think a secret was committed, rotate it first, then open an issue.

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private reporting:
**Security → Report a vulnerability** on the repository. Include the affected
route or file, reproduction steps, and impact. Expect an initial answer within a
week; this is a side project, not a company.

## Scope

In scope: credential leakage, host-validation bypass in `/api/download/proxy`
and `/api/stream/preview`, path traversal in ZIP naming, SSRF through upstream
URLs, denial of service through unbounded parsing.

Out of scope: the absence of API authentication (documented above), and
Looperman's own service.
