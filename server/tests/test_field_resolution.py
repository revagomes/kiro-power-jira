"""Tests for _resolve_field_id and custom_fields passthrough (spec change #2)."""

import pytest


FIELD_CATALOG = [
    {"id": "summary", "name": "Summary", "custom": False},
    {"id": "priority", "name": "Priority", "custom": False},
    {"id": "customfield_10001", "name": "Epic Link", "custom": True},
    {"id": "customfield_10002", "name": "Epic Link Status", "custom": True},
    {"id": "customfield_10004", "name": "Story Points", "custom": True},
]


def _install_field_catalog(jira, monkeypatch):
    """Mock _api_request so GET /field returns the catalog; count the calls."""
    counter = {"field_calls": 0, "posts": [], "puts": []}

    def fake(url, method="GET", payload=None):
        if url.endswith("/field") and method == "GET":
            counter["field_calls"] += 1
            return FIELD_CATALOG
        if method == "POST":
            counter["posts"].append((url, payload))
            return {"key": "TEST-1"}
        if method == "PUT":
            counter["puts"].append((url, payload))
            return {}
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    # Reset any module-level field cache between tests.
    if hasattr(jira, "_reset_field_cache"):
        jira._reset_field_cache()
    return counter


# ── _resolve_field_id ─────────────────────────────────────────────────────────

def test_resolve_exact_name(jira, monkeypatch):
    _install_field_catalog(jira, monkeypatch)
    assert jira._resolve_field_id("Epic Link") == "customfield_10001"


def test_resolve_is_case_insensitive_but_exact(jira, monkeypatch):
    _install_field_catalog(jira, monkeypatch)
    assert jira._resolve_field_id("epic link") == "customfield_10001"
    # Must not fuzzy-match the longer "Epic Link Status".
    assert jira._resolve_field_id("EPIC LINK") == "customfield_10001"


def test_resolve_raw_customfield_id_passthrough(jira, monkeypatch):
    counter = _install_field_catalog(jira, monkeypatch)
    assert jira._resolve_field_id("customfield_99999") == "customfield_99999"
    # Passthrough should not require fetching the catalog.
    assert counter["field_calls"] == 0


def test_resolve_unknown_name_raises_with_candidates(jira, monkeypatch):
    _install_field_catalog(jira, monkeypatch)
    with pytest.raises(ValueError) as exc:
        jira._resolve_field_id("Epic Lnik")
    msg = str(exc.value)
    assert "Epic Lnik" in msg
    # Should surface real field names to help the caller.
    assert "Epic Link" in msg


def test_resolve_caches_catalog_across_lookups(jira, monkeypatch):
    counter = _install_field_catalog(jira, monkeypatch)
    jira._resolve_field_id("Epic Link")
    jira._resolve_field_id("Story Points")
    assert counter["field_calls"] == 1  # fetched once, reused


def test_resolve_does_not_cache_errors(jira, monkeypatch):
    """A transient API error must not poison the cache for the session."""
    state = {"fail": True, "calls": 0}

    def fake(url, method="GET", payload=None):
        if url.endswith("/field") and method == "GET":
            state["calls"] += 1
            if state["fail"]:
                raise RuntimeError("JIRA API error (503): unavailable")
            return FIELD_CATALOG
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    if hasattr(jira, "_reset_field_cache"):
        jira._reset_field_cache()

    with pytest.raises(RuntimeError):
        jira._resolve_field_id("Epic Link")

    # Recover: next call should retry the fetch, not serve a cached failure.
    state["fail"] = False
    assert jira._resolve_field_id("Epic Link") == "customfield_10001"
    assert state["calls"] == 2


# ── custom_fields passthrough ───────────────────────────────────────────────

def test_create_custom_fields_by_name(jira, monkeypatch):
    counter = _install_field_catalog(jira, monkeypatch)
    jira.jira_create(summary="hi", custom_fields={"Story Points": 5})
    url, payload = counter["posts"][-1]
    assert payload["fields"]["customfield_10004"] == 5


def test_create_custom_fields_raw_id(jira, monkeypatch):
    counter = _install_field_catalog(jira, monkeypatch)
    jira.jira_create(summary="hi", custom_fields={"customfield_12345": "x"})
    url, payload = counter["posts"][-1]
    assert payload["fields"]["customfield_12345"] == "x"


def test_update_custom_fields_by_name(jira, monkeypatch):
    counter = _install_field_catalog(jira, monkeypatch)
    result = jira.jira_update("TEST-1", custom_fields={"Story Points": 8})
    url, payload = counter["puts"][-1]
    assert payload["fields"]["customfield_10004"] == 8
    assert "customfield_10004" in result["updated_fields"]


def test_typed_param_wins_over_custom_fields_collision(jira, monkeypatch):
    """Explicit typed param must win; collision reported, not silently merged."""
    counter = _install_field_catalog(jira, monkeypatch)
    result = jira.jira_create(
        summary="hi",
        priority="P1",
        custom_fields={"priority": {"name": "P4"}},
    )
    url, payload = counter["posts"][-1]
    assert payload["fields"]["priority"] == {"name": "P1"}
    assert "priority" in result.get("ignored_custom_fields", [])


def test_empty_custom_fields_is_noop(jira, monkeypatch):
    counter = _install_field_catalog(jira, monkeypatch)
    jira.jira_create(summary="hi", custom_fields={})
    url, payload = counter["posts"][-1]
    # No custom fields added; catalog not fetched for an empty map.
    assert counter["field_calls"] == 0
    assert "customfield_10004" not in payload["fields"]


def test_blank_custom_field_key_is_skipped(jira, monkeypatch):
    """A blank/whitespace-only key must not abort the whole create with a
    confusing 'Unknown field' error; it is skipped and reported as ignored."""
    counter = _install_field_catalog(jira, monkeypatch)
    result = jira.jira_create(
        summary="hi", custom_fields={"": 1, "   ": 2, "Story Points": 5}
    )
    url, payload = counter["posts"][-1]
    # The valid field still applied.
    assert payload["fields"]["customfield_10004"] == 5
    # Blank keys reported, not applied.
    assert "" in result.get("ignored_custom_fields", [])


def test_epic_link_and_custom_fields_same_id_collision(jira, monkeypatch):
    """epic_link is applied first; a custom_fields entry targeting the SAME
    resolved id must be reported as ignored, not silently overwrite it."""
    counter = _install_field_catalog(jira, monkeypatch)
    result = jira.jira_create(
        summary="hi",
        epic_link="TEST-100",
        custom_fields={"Epic Link": "TEST-999"},
    )
    url, payload = counter["posts"][-1]
    # epic_link wins.
    assert payload["fields"]["customfield_10001"] == "TEST-100"
    assert "Epic Link" in result.get("ignored_custom_fields", [])
