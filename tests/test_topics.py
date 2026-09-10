from types import SimpleNamespace

import anthropic
import pytest

from pintxos.topics import TOPICS, build_prompt, classify_topic, parse_topic

EXPECTED_SLUGS = [
    "arts",
    "conflict",
    "crime",
    "disaster",
    "economy",
    "education",
    "environment",
    "health",
    "human_interest",
    "labour",
    "lifestyle",
    "politics",
    "religion",
    "science",
    "society",
    "sport",
    "weather",
]


class FakeMessages:
    """Stands in for client.messages: returns `text`, or raises `error` if given."""

    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


class FakeClient:
    def __init__(self, text=None, error=None):
        self.messages = FakeMessages(text, error)


def _patch_client(monkeypatch, text=None, error=None):
    fake = FakeClient(text, error)
    # classify_topic() calls the _client imported into pintxos.topics, so patch it there.
    monkeypatch.setattr("pintxos.topics._client", lambda: fake)
    return fake


def _api_error():
    """An anthropic.APIError instance, built without touching the network."""
    return anthropic.APIError("boom", request=None, body=None)


# --- TOPICS ---------------------------------------------------------------


def test_topics_are_the_17_iptc_top_level_slugs():
    assert [slug for slug, _name, _definition in TOPICS] == EXPECTED_SLUGS


def test_topics_all_have_a_name_and_a_definition():
    for slug, name, definition in TOPICS:
        assert name.strip(), slug
        assert definition.strip(), slug


# --- parse_topic ----------------------------------------------------------


def test_parse_topic_exact_slug():
    assert parse_topic("sport") == "sport"


def test_parse_topic_quoted_and_punctuated():
    assert parse_topic('"sport".') == "sport"
    assert parse_topic("  `Human_Interest`  \n") == "human_interest"
    assert parse_topic("POLITICS!") == "politics"


def test_parse_topic_garbage_is_none():
    assert parse_topic("I think this is about football") is None
    assert parse_topic("") is None
    assert parse_topic("technology") is None


# --- build_prompt ---------------------------------------------------------


def test_build_prompt_system_lists_all_17_slugs():
    system, _user = build_prompt("Title", [], "")
    for slug, name, definition in TOPICS:
        assert f"{slug}: {name} - {definition}" in system


def test_build_prompt_user_carries_title_labels_and_lead():
    _system, user = build_prompt("Big match", ["sport", "football"], "It happened.")
    assert "Title: Big match" in user
    assert "Labels: sport, football" in user
    assert "Lead: It happened." in user


def test_build_prompt_omits_labels_and_lead_when_empty():
    _system, user = build_prompt("Big match", [], "")
    assert "Labels:" not in user
    assert "Lead:" not in user
    assert user == "Title: Big match"


def test_build_prompt_is_deterministic():
    first = build_prompt("Big match", ["sport"], "Lead text")
    second = build_prompt("Big match", ["sport"], "Lead text")
    assert first == second


# --- classify_topic -------------------------------------------------------


def test_classify_topic_returns_slug(monkeypatch):
    fake = _patch_client(monkeypatch, text="sport")
    assert classify_topic("Big match", ["football"], "Lead") == "sport"
    (call,) = fake.messages.calls
    assert call["max_tokens"] == 20
    _system, user = build_prompt("Big match", ["football"], "Lead")
    assert call["messages"] == [{"role": "user", "content": user}]


def test_classify_topic_tolerates_a_decorated_reply(monkeypatch):
    _patch_client(monkeypatch, text=' "weather".\n')
    assert classify_topic("Storm", [], "") == "weather"


def test_classify_topic_returns_none_on_api_error(monkeypatch, caplog):
    _patch_client(monkeypatch, error=_api_error())
    with caplog.at_level("WARNING", logger="pintxos"):
        assert classify_topic("Big match", [], "") is None
    assert caplog.records


def test_classify_topic_returns_none_on_garbage(monkeypatch, caplog):
    _patch_client(monkeypatch, text="probably something about sports, hard to say")
    with caplog.at_level("WARNING", logger="pintxos"):
        assert classify_topic("Big match", [], "") is None
    assert caplog.records


def test_classify_topic_propagates_missing_api_key(monkeypatch, tmp_path):
    from pintxos.summarize import MissingApiKey

    monkeypatch.setenv("PINTXOS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingApiKey):
        classify_topic("Big match", [], "")
