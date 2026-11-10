"""Thin Yahoo Fantasy API client: fetch -> scrub -> cache raw JSON -> return flattened tree.

Raw snapshots live in data/raw/yahoo/{scope}/{name}.json and are never overwritten
unless refresh=True (historic seasons are frozen). Emails are dropped and manager guids
are replaced with a stable one-way hash (guid_h) so the repo can be public.
"""
import hashlib
import json
import time
from pathlib import Path

import requests

from . import auth

BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
RAW_ROOT = Path("data/raw/yahoo")              # scrubbed, committed
PRIVATE_ROOT = Path("data/private/raw/yahoo")  # unscrubbed, gitignored
PAUSE = 0.25  # seconds between live calls


class YahooError(Exception):
    def __init__(self, status, body=""):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status


def scrub(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "email":
                continue
            if k == "guid":
                ok = isinstance(v, str) and v not in ("", "--")
                out["guid_h"] = hashlib.sha256(v.encode()).hexdigest()[:16] if ok else None
            else:
                out[k] = scrub(v)
        return out
    if isinstance(o, list):
        return [scrub(x) for x in o]
    return o


def flatten(o):
    """Collapse Yahoo's JSON quirks: {"0":{..},"1":{..},"count":2} -> list;
    [ {a}, {b}, [..] ] -> merged dict."""
    if isinstance(o, dict):
        keys = set(o)
        if "count" in keys and all(k.isdigit() for k in keys - {"count"}):
            return [flatten(o[k]) for k in sorted((k for k in keys if k != "count"), key=int)]
        return {k: flatten(v) for k, v in o.items()}
    if isinstance(o, list):
        items = [flatten(x) for x in o]
        items = [x for x in items if x != []]
        if items and all(isinstance(x, dict) for x in items):
            merged = {}
            for x in items:
                merged.update(x)
            return merged
        return items
    return o


def find_all(o, key):
    """All dicts stored under `key`, anywhere in the tree (no descent into a match)."""
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key and isinstance(v, dict):
                out.append(v)
            elif k == key and isinstance(v, list):
                out.extend(x for x in v if isinstance(x, dict))
            else:
                out.extend(find_all(v, key))
    elif isinstance(o, list):
        for x in o:
            out.extend(find_all(x, key))
    return out


def first(o, key):
    r = find_all(o, key)
    return r[0] if r else {}


def _live_get(path, retries=5):
    url = f"{BASE}/{path}"
    last = None
    for attempt in range(retries):
        r = requests.get(url, params={"format": "json"},
                         headers={"Authorization": f"Bearer {auth.access_token()}"}, timeout=30)
        if r.status_code == 200:
            time.sleep(PAUSE)
            return r.json()
        last = r
        if r.status_code == 401:
            auth.refresh()
        elif r.status_code in (429, 999) or r.status_code >= 500:
            time.sleep(2 ** attempt)
        else:
            break
    raise YahooError(last.status_code, last.text)


def fetch(path, scope, name, refresh=False):
    """Return the flattened response for `path`, from the raw cache when present."""
    f = RAW_ROOT / scope / f"{name}.json"
    if f.exists() and not refresh:
        return flatten(json.loads(f.read_text()))
    live = _live_get(path)
    # Unscrubbed copy stays local (gitignored) so you can identify owners by email/guid.
    p = PRIVATE_ROOT / scope / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(live, indent=1, sort_keys=True))
    raw = scrub(live)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(raw, indent=1, sort_keys=True))
    return flatten(raw)


def load_private(scope, name):
    """Unscrubbed flattened response, or None if there is no local private copy."""
    p = PRIVATE_ROOT / scope / f"{name}.json"
    return flatten(json.loads(p.read_text())) if p.exists() else None
