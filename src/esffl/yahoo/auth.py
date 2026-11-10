"""Yahoo OAuth2 (authorization-code flow). Local use only; nothing here runs in CI.

One-time:  PYTHONPATH=src python -m esffl.yahoo.auth
Writes .yahoo_token.json (gitignored). access_token() refreshes automatically.
"""
import json
import os
import time
import urllib.parse
from pathlib import Path

import requests

TOKEN_FILE = Path(".yahoo_token.json")
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _creds():
    load_env()
    cid = os.environ.get("YAHOO_CLIENT_ID")
    sec = os.environ.get("YAHOO_CLIENT_SECRET")
    redirect = os.environ.get("YAHOO_REDIRECT_URI", "https://localhost:8080")
    if not cid or not sec:
        raise SystemExit("Set YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET in .env (see .env.example).")
    return cid, sec, redirect


def _token_request(data):
    cid, sec, _ = _creds()
    r = requests.post(TOKEN_URL, data=data, auth=(cid, sec), timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Token request failed: {r.status_code} {r.text[:300]}")
    tok = r.json()
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
    # Yahoo may omit refresh_token on refresh; keep the old one.
    if "refresh_token" not in tok and TOKEN_FILE.exists():
        tok["refresh_token"] = json.loads(TOKEN_FILE.read_text()).get("refresh_token")
    TOKEN_FILE.write_text(json.dumps(tok))
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return tok


def refresh():
    if not TOKEN_FILE.exists():
        raise SystemExit("No token yet. Run: PYTHONPATH=src python -m esffl.yahoo.auth")
    old = json.loads(TOKEN_FILE.read_text())
    _, _, redirect = _creds()
    return _token_request({"grant_type": "refresh_token",
                           "refresh_token": old["refresh_token"],
                           "redirect_uri": redirect})


def access_token():
    if not TOKEN_FILE.exists():
        raise SystemExit("No token yet. Run: PYTHONPATH=src python -m esffl.yahoo.auth")
    tok = json.loads(TOKEN_FILE.read_text())
    if tok.get("expires_at", 0) - 60 < time.time():
        tok = refresh()
    return tok["access_token"]


def main():
    cid, _, redirect = _creds()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect,
        "response_type": "code", "language": "en-us"})
    print("1. Open this URL in a browser signed in as the Yahoo account in the league:\n")
    print(url)
    print("\n2. Approve. The redirect page will fail to load; that's expected.")
    print("   Copy the FULL URL from the address bar (or just the code= value) and paste it here.\n")
    raw = input("Redirected URL or code: ").strip()
    code = raw
    if "code=" in raw:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)["code"][0]
    _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect})
    print(f"Saved {TOKEN_FILE}. Do not commit it (it's gitignored).")


if __name__ == "__main__":
    main()
