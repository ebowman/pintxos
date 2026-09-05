"""Tests for the per-feed retry-fallback route and pintxos.poll.retry_fallback."""

from __future__ import annotations

from fastapi.testclient import TestClient

import pintxos.app as app_module
from pintxos import poll
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


def _item_rows(feed_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM items WHERE feed_id = ? ORDER BY id", (feed_id,)
        ).fetchall()


def test_retry_fallback_route_queues_retry_and_leaves_rows_in_place(monkeypatch):
    """The route never deletes: rows stay put, retry_one is queued instead."""
    feed_id = _seed_with_fallback()
    calls = []
    monkeypatch.setattr(app_module, "retry_one", lambda fid: calls.append(fid))
    with TestClient(app) as c:
        resp = c.post(f"/feeds/{feed_id}/retry-fallback", follow_redirects=False)

    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "Retrying" in location
    assert "2" in location

    rows = _item_rows(feed_id)
    assert {r["guid"] for r in rows} == {"guid-1", "guid-2", "guid-3"}

    assert calls == [feed_id]


def test_retry_fallback_route_no_fallback_items(monkeypatch):
    feed_id = _seed_no_fallback()
    calls = []
    monkeypatch.setattr(app_module, "retry_one", lambda fid: calls.append(fid))
    with TestClient(app) as c:
        resp = c.post(f"/feeds/{feed_id}/retry-fallback", follow_redirects=False)

    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "No fallback items" in location or "No%20fallback%20items" in location

    assert calls == []

    rows = _item_rows(feed_id)
    assert {r["guid"] for r in rows} == {"guid-1"}


def test_retry_fallback_route_singular_flash_message(monkeypatch):
    feed_id = _seed_single_fallback()
    monkeypatch.setattr(app_module, "retry_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.post(f"/feeds/{feed_id}/retry-fallback", follow_redirects=False)
    location = resp.headers["location"]
    assert "Retrying%201%20item" in location or "Retrying 1 item" in location


def test_retry_fallback_route_unknown_feed(monkeypatch):
    monkeypatch.setattr(app_module, "retry_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.post("/feeds/999/retry-fallback", follow_redirects=False)
    assert resp.status_code == 404


def test_feed_edit_page_shows_retry_form(monkeypatch):
    feed_id = _seed_with_fallback()
    monkeypatch.setattr(app_module, "retry_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.get(f"/feeds/{feed_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "Retry 2 fallback items" in body


def test_feed_edit_page_hides_retry_form_when_no_fallback(monkeypatch):
    feed_id = _seed_no_fallback()
    monkeypatch.setattr(app_module, "retry_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.get(f"/feeds/{feed_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "retry-fallback" not in body


def test_feed_edit_page_singular_fallback_label(monkeypatch):
    feed_id = _seed_single_fallback()
    monkeypatch.setattr(app_module, "retry_one", lambda fid: None)
    with TestClient(app) as c:
        resp = c.get(f"/feeds/{feed_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "Retry 1 fallback item" in body
    assert "Retry 1 fallback items" not in body


# --- pintxos.poll.retry_fallback: direct unit tests -------------------------


def test_retry_fallback_updates_row_in_place_on_success(monkeypatch):
    """A fallback item whose article now fetches is updated, not replaced or deleted."""
    feed_id = _seed_single_fallback()

    monkeypatch.setattr(poll, "fetch_article", lambda link: "FULL ARTICLE TEXT " * 20)
    monkeypatch.setattr(
        poll, "summarize", lambda text, original_title, url: ("New Headline", "New summary")
    )

    poll.retry_fallback(feed_id)

    rows = _item_rows(feed_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["guid"] == "guid-1"  # same row, not a new insert
    assert row["fallback"] == 0
    assert row["headline"] == "New Headline"
    assert row["summary"] == "New summary"
    assert row["auth"] is None  # no cookies loaded for this link
    assert row["word_count"] is not None
    assert feed_id not in poll._status


def test_retry_fallback_records_auth_and_leaves_fallback_on_repeat_failure(monkeypatch):
    """A fallback item whose fetch still fails stays a fallback item, auth updated only."""
    feed_id = _seed_single_fallback()

    monkeypatch.setattr(poll, "fetch_article", lambda link: None)

    def boom_summarize(*_args, **_kwargs):
        raise AssertionError("summarize should not be called when the fetch fails")

    monkeypatch.setattr(poll, "summarize", boom_summarize)

    poll.retry_fallback(feed_id)

    rows = _item_rows(feed_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["guid"] == "guid-1"
    assert row["fallback"] == 1
    assert row["headline"] == "Headline One"  # unchanged
    assert row["summary"] == "Summary one."  # unchanged
    assert row["auth"] == "missing"  # no cookies loaded, fetch failed
    assert feed_id not in poll._status


def test_retry_fallback_only_touches_fallback_rows_for_this_feed(monkeypatch):
    """Non-fallback rows and other feeds' rows are left untouched."""
    feed_id = _seed_with_fallback()

    with db() as conn:
        other_feed_id = conn.execute(
            "INSERT INTO feeds(url, title, created_at) VALUES (?, ?, ?)",
            ("https://other.example.com/feed.xml", "Other Feed", now()),
        ).lastrowid
        conn.execute(
            """INSERT INTO items
            (feed_id, guid, link, original_title, published_at, headline, summary,
             fallback, auth, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                other_feed_id,
                "other-guid-1",
                "https://other.example.com/1",
                "Other Original",
                "2026-09-01T12:00:00+00:00",
                "Other Headline",
                "Other summary.",
                1,
                None,
                now(),
            ),
        )

    monkeypatch.setattr(poll, "fetch_article", lambda link: "FULL ARTICLE TEXT " * 20)
    monkeypatch.setattr(
        poll, "summarize", lambda text, original_title, url: ("New Headline", "New summary")
    )

    poll.retry_fallback(feed_id)

    with db() as conn:
        guid3 = conn.execute(
            "SELECT * FROM items WHERE feed_id = ? AND guid = ?", (feed_id, "guid-3")
        ).fetchone()
        other_row = conn.execute(
            "SELECT * FROM items WHERE feed_id = ? AND guid = ?",
            (other_feed_id, "other-guid-1"),
        ).fetchone()

    assert guid3["fallback"] == 0
    assert guid3["headline"] == "Headline Three"  # never touched: wasn't fallback=1

    assert other_row["fallback"] == 1
    assert other_row["headline"] == "Other Headline"  # untouched: different feed


def test_retry_fallback_missing_api_key_stops_without_deleting(monkeypatch):
    from pintxos.summarize import MissingApiKey

    feed_id = _seed_single_fallback()

    monkeypatch.setattr(poll, "fetch_article", lambda link: "FULL ARTICLE TEXT " * 20)

    def boom(*_args, **_kwargs):
        raise MissingApiKey("ANTHROPIC_API_KEY not set")

    monkeypatch.setattr(poll, "summarize", boom)

    poll.retry_fallback(feed_id)

    rows = _item_rows(feed_id)
    assert len(rows) == 1
    assert rows[0]["fallback"] == 1  # left as-is, not deleted

    with db() as conn:
        feed = conn.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,)).fetchone()
    assert feed["last_error"] == "ANTHROPIC_API_KEY not set"


def test_retry_fallback_summarize_error_skips_and_keeps_row(monkeypatch):
    from pintxos.summarize import SummarizeError

    feed_id = _seed_single_fallback()

    monkeypatch.setattr(poll, "fetch_article", lambda link: "FULL ARTICLE TEXT " * 20)

    def flaky(*_args, **_kwargs):
        raise SummarizeError("API said no")

    monkeypatch.setattr(poll, "summarize", flaky)

    poll.retry_fallback(feed_id)

    rows = _item_rows(feed_id)
    assert len(rows) == 1
    assert rows[0]["guid"] == "guid-1"
    assert rows[0]["fallback"] == 1  # unchanged: not deleted, still retryable later


def test_retry_one_queues_retry_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(poll, "retry_fallback", lambda fid: calls.append(fid))

    class FakeScheduler:
        def add_job(self, func, args, id, replace_existing, misfire_grace_time):
            calls.append(("queued", id))

    monkeypatch.setattr(poll, "scheduler", FakeScheduler())
    poll.retry_one(42)
    assert ("queued", "retry-42") in calls
