"""Tests for the per-feed retry-fallback route."""

from __future__ import annotations

from fastapi.testclient import TestClient

import pintxos.app as app_module
from pintxos.app import app
from pintxos.db import db, now

FEED_URL = "https://example.com/feed.xml"


def _seed_with_fallback():
    """Feed with two fallback items (one auth='missing', one auth=NULL) and
    one non-fallback item (auth='used')."""
    with db() as conn:
        feed_id = conn.execute(
            "INSERT INTO feeds(url, title, created_at) VALUES (?, ?, ?)",
            (FEED_URL, "Example Feed", now()),
        ).lastrowid
        conn.execute(
            """INSERT INTO items
            (feed_id, guid, link, original_title, published_at, headline, summary,
             fallback, auth, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feed_id,
                "guid-1",
                "https://example.com/1",
                "Original One",
                "2026-09-01T12:00:00+00:00",
                "Headline One",
                "Summary one.",
                1,
                "missing",
                now(),
            ),
        )
        conn.execute(
            """INSERT INTO items
            (feed_id, guid, link, original_title, published_at, headline, summary,
             fallback, auth, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feed_id,
                "guid-2",
                "https://example.com/2",
                "Original Two",
                "2026-09-02T12:00:00+00:00",
                "Headline Two",
                "Summary two.",
                1,
                None,
                now(),
            ),
        )
        conn.execute(
            """INSERT INTO items
            (feed_id, guid, link, original_title, published_at, headline, summary,
             fallback, auth, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feed_id,
                "guid-3",
                "https://example.com/3",
                "Original Three",
                "2026-09-03T12:00:00+00:00",
                "Headline Three",
                "Summary three.",
                0,
                "used",
                now(),
            ),
        )
    return feed_id


def _seed_no_fallback():
    with db() as conn:
        feed_id = conn.execute(
            "INSERT INTO feeds(url, title, created_at) VALUES (?, ?, ?)",
            (FEED_URL, "Example Feed", now()),
        ).lastrowid
        conn.execute(
            """INSERT INTO items
            (feed_id, guid, link, original_title, published_at, headline, summary,
             fallback, auth, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feed_id,
                "guid-1",
                "https://example.com/1",
                "Original One",
                "2026-09-01T12:00:00+00:00",
                "Headline One",
                "Summary one.",
                0,
                "used",
                now(),
            ),
        )
    return feed_id


def _seed_single_fallback():
    with db() as conn:
        feed_id = conn.execute(
            "INSERT INTO feeds(url, title, created_at) VALUES (?, ?, ?)",
            (FEED_URL, "Example Feed", now()),
        ).lastrowid
        conn.execute(
            """INSERT INTO items
            (feed_id, guid, link, original_title, published_at, headline, summary,
             fallback, auth, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feed_id,
                "guid-1",
                "https://example.com/1",
                "Original One",
                "2026-09-01T12:00:00+00:00",
                "Headline One",
                "Summary one.",
                1,
                None,
                now(),
            ),
        )
    return feed_id


def test_retry_fallback_deletes_and_polls(monkeypatch):
    feed_id = _seed_with_fallback()
    calls = []
    monkeypatch.setattr(app_module, "poll_one", lambda fid: calls.append(fid))
    with TestClient(app) as c:
        resp = c.post(f"/feeds/{feed_id}/retry-fallback", follow_redirects=False)

    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "Retrying" in location
    assert "2" in location
    assert "items" in location

    with db() as conn:
        rows = conn.execute(
            "SELECT guid FROM items WHERE feed_id = ?", (feed_id,)
        ).fetchall()
    remaining = {r["guid"] for r in rows}
    assert remaining == {"guid-3"}

    assert calls == [feed_id]


def test_retry_fallback_no_fallback_items(monkeypatch):
    feed_id = _seed_no_fallback()
    calls = []
    monkeypatch.setattr(app_module, "poll_one", lambda fid: calls.append(fid))
    with TestClient(app) as c:
        resp = c.post(f"/feeds/{feed_id}/retry-fallback", follow_redirects=False)

    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "No fallback items" in location or "No%20fallback%20items" in location

    assert calls == []

    with db() as conn:
        rows = conn.execute(
            "SELECT guid FROM items WHERE feed_id = ?", (feed_id,)
        ).fetchall()
    assert {r["guid"] for r in rows} == {"guid-1"}


def test_retry_fallback_unknown_feed(monkeypatch):
    monkeypatch.setattr(app_module, "poll_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.post("/feeds/999/retry-fallback", follow_redirects=False)
    assert resp.status_code == 404


def test_retry_fallback_singular_message(monkeypatch):
    feed_id = _seed_single_fallback()
    calls = []
    monkeypatch.setattr(app_module, "poll_one", lambda fid: calls.append(fid))
    with TestClient(app) as c:
        resp = c.post(f"/feeds/{feed_id}/retry-fallback", follow_redirects=False)

    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "Retrying%201%20item" in location or "Retrying 1 item" in location
    assert "1 items" not in location.replace("%20", " ")

    assert calls == [feed_id]


def test_feed_edit_page_shows_retry_form(monkeypatch):
    feed_id = _seed_with_fallback()
    monkeypatch.setattr(app_module, "poll_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.get(f"/feeds/{feed_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "Retry 2 fallback items" in body
    assert "1 of them may need a login" in body


def test_feed_edit_page_hides_retry_form_when_no_fallback(monkeypatch):
    feed_id = _seed_no_fallback()
    monkeypatch.setattr(app_module, "poll_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.get(f"/feeds/{feed_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "retry-fallback" not in body


def test_feed_edit_page_singular_fallback_label(monkeypatch):
    feed_id = _seed_single_fallback()
    monkeypatch.setattr(app_module, "poll_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.get(f"/feeds/{feed_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "Retry 1 fallback item" in body
    assert "Retry 1 fallback items" not in body
