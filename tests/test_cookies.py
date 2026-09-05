"""Tests for pintxos.cookies: loading and caching a Netscape cookies.txt.

The module cache (`pintxos.cookies._cache`) is keyed on
(str(path), st_mtime_ns, st_size), and `path` comes from
`data_dir() / "cookies.txt"`. Since `tests/conftest.py`'s autouse
`_isolated_data_dir` fixture points PINTXOS_DATA_DIR at a fresh tmp_path
per test, every test naturally gets its own path and therefore its own
cache key -- no explicit cache-clearing fixture is needed. We still reset
`pintxos.cookies._cache` to None in an autouse fixture below, purely for
extra safety/clarity (so a stale cache entry can never leak across tests
even if paths were ever to collide).
"""

from __future__ import annotations

import os

import pytest

import pintxos.cookies as cookies_mod
from pintxos.cookies import cookie_path, get_jar, has_cookies_for, load_jar, summary

# Well into the future so cookies are never seen as expired.
FUTURE_EXPIRY = 4102444800  # 2100-01-01T00:00:00Z
FUTURE_EXPIRY_2 = 4102531200  # 2100-01-02T00:00:00Z
PAST_EXPIRY = 946684800  # 2000-01-01T00:00:00Z, well in the past


@pytest.fixture(autouse=True)
def _reset_cache():
    cookies_mod._cache = None
    yield
    cookies_mod._cache = None


def _write(path, lines):
    path.write_text("# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n")


def test_no_file_load_jar_and_get_jar_are_none():
    assert load_jar() is None
    assert get_jar() is None


def test_two_domains_loaded_and_summarized():
    path = cookie_path()
    _write(
        path,
        [
            f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tabc",
            f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tuid\tdef",
            f".economist.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tghi",
        ],
    )

    jar = get_jar()
    assert jar is not None
    assert len(jar) == 3

    result = summary(jar)
    assert result == [
        {"domain": ".economist.com", "count": 1, "expires": "2100-01-01"},
        {"domain": ".ft.com", "count": 2, "expires": "2100-01-01"},
    ]


def test_malformed_file_logs_one_warning_without_contents(caplog):
    path = cookie_path()
    path.write_text('{"not": "cookies"}')

    with caplog.at_level("WARNING"):
        result = load_jar()

    assert result is None

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "cookies.txt" in message
    assert '{"not": "cookies"}' not in message  # file contents must never be logged


def test_reload_on_mtime_change_and_removal_clears_cache():
    path = cookie_path()
    _write(
        path,
        [
            f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tabc",
            f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tuid\tdef",
            f".economist.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tghi",
        ],
    )

    jar = get_jar()
    assert jar is not None
    assert len(jar) == 3

    t = path.stat().st_mtime
    _write(
        path,
        [
            f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tabc",
            f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tuid\tdef",
            f".economist.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tghi",
            f".example.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tjkl",
        ],
    )
    os.utime(path, (t + 2, t + 2))

    jar = get_jar()
    assert jar is not None
    assert len(jar) == 4

    path.unlink()
    assert get_jar() is None


def test_expired_cookie_dropped_session_cookie_kept():
    path = cookie_path()
    _write(
        path,
        [
            # Session cookie: Netscape convention represents "no expiry"
            # with an *empty* expires field (not "0" -- see note below).
            ".ft.com\tTRUE\t/\tFALSE\t\tsess\tabc",
            f".ft.com\tTRUE\t/\tFALSE\t{PAST_EXPIRY}\told\tdef",
        ],
    )

    jar = get_jar()
    assert jar is not None
    assert len(jar) == 1
    assert jar._cookies[".ft.com"]["/"]["sess"] is not None

    result = summary(jar)
    assert result == [{"domain": ".ft.com", "count": 1, "expires": None}]


def test_has_cookies_for_leading_dot_domain_matches_subdomain_and_bare():
    path = cookie_path()
    _write(path, [f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tabc"])
    jar = get_jar()

    assert has_cookies_for(jar, "https://www.ft.com/a") is True
    assert has_cookies_for(jar, "https://ft.com/a") is True
    assert has_cookies_for(jar, "https://www.example.com/a") is False
    assert has_cookies_for(jar, "https://notft.com/a") is False


def test_has_cookies_for_host_only_cookie_matches_only_that_host():
    path = cookie_path()
    _write(path, [f"www.economist.com\tFALSE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tabc"])
    jar = get_jar()

    assert has_cookies_for(jar, "https://www.economist.com/a") is True
    assert has_cookies_for(jar, "https://economist.com/a") is False


def test_has_cookies_for_none_or_empty_jar_is_false():
    assert has_cookies_for(None, "https://www.ft.com/a") is False

    path = cookie_path()
    path.write_text("# Netscape HTTP Cookie File\n")
    jar = get_jar()
    assert has_cookies_for(jar, "https://www.ft.com/a") is False


def test_has_cookies_for_url_without_host_is_false():
    path = cookie_path()
    _write(path, [f".ft.com\tTRUE\t/\tFALSE\t{FUTURE_EXPIRY}\tsid\tabc"])
    jar = get_jar()

    assert has_cookies_for(jar, "not-a-url") is False
