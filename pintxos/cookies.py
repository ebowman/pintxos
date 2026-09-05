"""Load a Netscape-format cookies.txt from the data directory.

The file is optional: most installs never have one, and its absence is
not an error. When present, it is loaded with `http.cookiejar`'s built-in
Netscape parser (`MozillaCookieJar`). `get_jar` caches the parsed jar,
keyed on the file's path, mtime and size, so repeated calls (e.g. once
per poll) don't re-parse an unchanged file -- but a change in mtime/size,
or the file appearing after being absent, triggers a reload. A failed
parse is cached too, so a persistently malformed file doesn't get
re-logged and re-attempted on every call.

Never logs cookie names or values -- only the file path, on failure.
"""

from __future__ import annotations

import http.cookiejar
import logging
from datetime import datetime, timezone
from pathlib import Path

from pintxos.config import data_dir

log = logging.getLogger("pintxos")

# Cache key: (str(path), st_mtime_ns, st_size) -> cached jar (or None on failed load).
_cache: tuple[tuple[str, int, int], http.cookiejar.MozillaCookieJar | None] | None = None


def cookie_path() -> Path:
    """Path to the cookies.txt file in the data directory."""
    return data_dir() / "cookies.txt"


def load_jar() -> http.cookiejar.MozillaCookieJar | None:
    """Load cookies.txt fresh from disk. None if missing or unparseable."""
    path = cookie_path()
    if not path.exists():
        return None
    jar = http.cookiejar.MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=False)
    except (http.cookiejar.LoadError, OSError):
        log.warning("cookies.txt at %s could not be loaded as a Netscape cookie file", path)
        return None
    return jar


def get_jar() -> http.cookiejar.MozillaCookieJar | None:
    """Cached cookie jar, reloaded when cookies.txt changes (by mtime/size).

    Returns None if the file is missing. A failed load is cached under the
    same key as the attempt that produced it, so it is not retried on every
    call while the file remains unchanged.
    """
    global _cache

    path = cookie_path()
    try:
        stat = path.stat()
    except OSError:
        _cache = None
        return None

    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _cache is not None and _cache[0] == key:
        return _cache[1]

    jar = load_jar()
    _cache = (key, jar)
    return jar


def summary(jar: http.cookiejar.MozillaCookieJar | None) -> list[dict]:
    """Per-domain cookie counts and earliest non-session expiry.

    Returns one dict per domain present in `jar`:
    `{"domain": str, "count": int, "expires": str | None}`, where `expires`
    is the ISO date (YYYY-MM-DD, UTC) of the earliest non-session cookie
    for that domain, or None if every cookie for that domain is a session
    cookie (no expiry). Sorted by domain. Never includes cookie names or
    values.
    """
    if jar is None:
        return []

    counts: dict[str, int] = {}
    earliest_expires: dict[str, int] = {}
    for cookie in jar:
        counts[cookie.domain] = counts.get(cookie.domain, 0) + 1
        if cookie.expires is not None:
            current = earliest_expires.get(cookie.domain)
            if current is None or cookie.expires < current:
                earliest_expires[cookie.domain] = cookie.expires

    result = []
    for domain in sorted(counts):
        expires_epoch = earliest_expires.get(domain)
        expires = (
            datetime.fromtimestamp(expires_epoch, tz=timezone.utc).date().isoformat()
            if expires_epoch is not None
            else None
        )
        result.append({"domain": domain, "count": counts[domain], "expires": expires})
    return result
