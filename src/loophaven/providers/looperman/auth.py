import requests
import re
import json
import os
import pathlib
import time
from bs4 import BeautifulSoup

BASE = "https://www.looperman.com"
LOGIN_URL = f"{BASE}/account/login"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def _default_session_path():
    override = os.environ.get("LOOPHAVEN_SESSION_FILE")
    if override:
        return pathlib.Path(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return pathlib.Path(base) / "loophaven" / "session.json"


def _load_env_file():
    """Read a nearby .env so the service can log itself back in.

    python-dotenv is not a dependency here, and nothing else loaded the file:
    once the persisted cookie expired, the API could only ever report
    ``logged_in: false`` and downloads failed for good. Values already present
    in the real environment always win; nothing is ever printed.
    """
    explicit = os.environ.get("LOOPHAVEN_ENV_FILE")
    candidates = []
    if explicit:
        candidates.append(pathlib.Path(explicit))
    here = pathlib.Path(__file__).resolve()
    candidates.extend(parent / ".env" for parent in list(here.parents)[:8])
    candidates.append(pathlib.Path.cwd() / ".env")
    for path in candidates:
        try:
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip().strip('"').strip("'")
            return
        except OSError:
            continue


SESSION_PATH = _default_session_path()

# Global session storage (single user in sandbox - for multi-user you'd use redis/jwt)
_session_data = {
    "session": None,
    "logged_in": False,
    "email": None,
    "user_id": None,
    "username": None,
    "cookies_ok": False,
}

def get_session():
    """Return requests.Session or create new"""
    if _session_data["session"] is None:
        _session_data["session"] = requests.Session()
        _session_data["session"].headers.update(HEADERS)
    return _session_data["session"]

def is_logged_in():
    return _session_data["logged_in"] and _session_data["session"] is not None


def _save_session():
    """Persist cookies so a service restart does not silently log the user out."""
    session = _session_data.get("session")
    if session is None:
        return
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps({
            "saved_at": time.time(),
            "user_id": _session_data.get("user_id"),
            "username": _session_data.get("username"),
            "cookies": requests.utils.dict_from_cookiejar(session.cookies),
        }, indent=1), encoding="utf-8")
        try:
            os.chmod(SESSION_PATH, 0o600)
        except OSError:
            pass
    except Exception:
        pass


def _verify_session(session):
    """True/False when Looperman answers; None when the check itself failed.

    ``/account/`` is the member account page: anonymous visitors are
    redirected to ``/account/login``, members get their own profile link.

    The previous check looked for ``/account/logout`` on ``/loops``, but that
    link ships in the markup even when logged out — so an expired cookie still
    looked valid, ``/api/health`` claimed ``logged_in: true``, and every WAV
    download then failed with "no download link on the page".
    """
    try:
        response = session.get(f"{BASE}/account/", headers=HEADERS, timeout=10)
    except Exception:
        return None
    if response.status_code != 200:
        return None
    return "/account/login" not in response.url


def _load_session():
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    cookies = data.get("cookies") or {}
    if not cookies:
        return False
    session = get_session()
    requests.utils.cookiejar_from_dict(cookies, session.cookies)
    _session_data.update({"logged_in": True, "user_id": data.get("user_id"),
                          "username": data.get("username")})
    valid = _verify_session(session)
    if valid is False:
        _session_data.update({"logged_in": False, "user_id": None, "username": None,
                              "session": None})
        return False
    return True


def ensure_login():
    """Restore a persisted session, else log in from env vars. Never raises."""
    if _session_data["logged_in"] and _session_data["session"] is not None:
        return get_status()
    if _load_session():
        return get_status()
    _load_env_file()
    email = os.environ.get("LOOPERMAN_EMAIL")
    password = os.environ.get("LOOPERMAN_PASSWORD")
    if email and password:
        login(email, password)
    return get_status()

def get_status():
    username = _session_data["username"]
    if username and "@" in username:
        username = None
    return {
        "logged_in": _session_data["logged_in"],
        "username": username,
        "user_id": _session_data["user_id"],
    }

def relogin():
    """Force a fresh login from the env credentials.

    Used when a persisted cookie expires while the service is running: the
    in-memory state still says "logged in", so ensure_login() would do nothing
    and downloads would keep failing with "no download link".
    """
    email = os.environ.get("LOOPERMAN_EMAIL")
    password = os.environ.get("LOOPERMAN_PASSWORD")
    if not (email and password):
        _load_env_file()
        email = os.environ.get("LOOPERMAN_EMAIL")
        password = os.environ.get("LOOPERMAN_PASSWORD")
    if not (email and password):
        return False
    _session_data.update({"session": None, "logged_in": False,
                          "user_id": None, "username": None})
    result = login(email, password)
    return bool(result.get("success"))


def logout():
    _session_data["session"] = None
    _session_data["logged_in"] = False
    _session_data["email"] = None
    _session_data["username"] = None
    _session_data["user_id"] = None
    try:
        SESSION_PATH.unlink()
    except OSError:
        pass
    return {"success": True, "message": "logged out"}

def login(email, password):
    """
    Perform Looperman login: GET csrftoken + page_token, then POST credentials
    """
    try:
        session = get_session()
        # Step 1: GET login page to get tokens & cookies
        r = session.get(LOGIN_URL, timeout=15)
        if r.status_code != 200:
            return {"success": False, "error": f"GET login failed: {r.status_code}"}
        
        soup = BeautifulSoup(r.text, "lxml")
        csrftoken_el = soup.find("input", {"name": "csrftoken"})
        page_token_el = soup.find("input", {"name": "page_token"})
        
        csrftoken = csrftoken_el.get("value") if csrftoken_el else ""
        page_token = page_token_el.get("value") if page_token_el else ""
        
        if not csrftoken:
            # fallback: try extracting from JS var csrfToken
            m = re.search(r"var\s+csrfToken\s*=\s*'([^']+)'", r.text)
            if m:
                csrftoken = m.group(1)
        
        if not csrftoken:
            return {"success": False, "error": "could not extract csrftoken (Looperman may have changed)"}
        
        # Step 2: POST login
        data = {
            'csrftoken': csrftoken,
            'page_token': page_token,
            'user_email': email,
            'upass': password,
            'user_remember_code': '1',
            'user_disclaimer': '1',
            'submit': 'submit'
        }
        headers = {
            'Origin': BASE,
            'Referer': LOGIN_URL,
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': HEADERS['User-Agent'],
        }
        resp = session.post(LOGIN_URL, data=data, headers=headers, timeout=15, allow_redirects=True)

        # Verify on /account/: anonymous visitors are redirected to
        # /account/login. The old check ("is there any /users/profile link?")
        # was always true, because listing pages link to their authors.
        account = session.get(f"{BASE}/account/", headers=HEADERS, timeout=15)
        account_soup = BeautifulSoup(account.text, "lxml")
        account_link = account_soup.find("a", href=re.compile(r"/users/profile/\d+"))
        page_text = resp.text.lower()

        if "/account/login" not in account.url and account_link is not None:
            # Extract username/user_id
            user_id = None
            username = None
            href = account_link.get("href")
            m = re.search(r"/users/profile/(\d+)", href or "")
            if m:
                user_id = m.group(1)
            # try to get username from profile link text or from page
            # Look for logged-in user display
            # The nav account may have username
            username = account_link.get_text(strip=True) or email.split("@")[0]
            
            # Also try to find username via title or header
            if not username:
                title_match = re.search(r"Welcome.*?(\w+)", resp.text)
                if title_match:
                    username = title_match.group(1)
            
            _session_data["logged_in"] = True
            _session_data["email"] = email
            _session_data["user_id"] = user_id
            _session_data["username"] = username or email
            _save_session()
            
            return {
                "success": True,
                "message": f"logged in as {username or email}",
                "user_id": user_id,
                "username": username,
                "email": email,
            }
        else:
            # Check specific error
            err_msg = "wrong email or password"
            has_error_text = "invalid" in page_text and "email" in page_text and "password" in page_text
            if "too many" in page_text or "limit" in page_text:
                err_msg = "too many attempts - try again later"
            elif has_error_text:
                err_msg = "invalid credentials"
            
            # Debug: save response snippet
            snippet = resp.text[:800]
            return {
                "success": False,
                "error": err_msg,
                "debug_status": resp.status_code,
                "debug_url": resp.url,
            }
            
    except Exception as e:
        return {"success": False, "error": str(e)}

def authenticated_get(url, **kwargs):
    """GET with logged-in session if available, else normal"""
    sess = get_session()
    return sess.get(url, headers=HEADERS, timeout=kwargs.get("timeout", 15))

def authenticated_session():
    return get_session()
