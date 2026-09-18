"""Tests for the epic_link convenience parameter (spec change #3)."""

import pytest


CATALOG_WITH_EPIC = [
    {"id": "customfield_10001", "name": "Epic Link", "custom": True},
]
CATALOG_WITHOUT_EPIC = [
    {"id": "customfield_10004", "name": "Story Points", "custom": True},
]


def _install(jira, monkeypatch, catalog):
    captured = {"posts": [], "puts": []}

    def fake(url, method="GET", payload=None):
        if url.endswith("/field") and method == "GET":
            return catalog
        if method == "POST":
            captured["posts"].append((url, payload))
            return {"key": "TEST-1"}
        if method == "PUT":
            captured["puts"].append((url, payload))
            return {}
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    jira._reset_field_cache()
    return captured


def test_create_with_epic_link_sets_resolved_field(jira, monkeypatch):
    cap = _install(jira, monkeypatch, CATALOG_WITH_EPIC)
    jira.jira_create(summary="hi", epic_link="TEST-100")
    _, payload = cap["posts"][-1]
    assert payload["fields"]["customfield_10001"] == "TEST-100"


def test_update_with_epic_link_sets_resolved_field(jira, monkeypatch):
    cap = _install(jira, monkeypatch, CATALOG_WITH_EPIC)
    result = jira.jira_update("TEST-1", epic_link="TEST-100")
    _, payload = cap["puts"][-1]
    assert payload["fields"]["customfield_10001"] == "TEST-100"
    assert "customfield_10001" in result["updated_fields"]


def test_epic_link_unresolved_raises_clear_error(jira, monkeypatch):
    """Instances without an 'Epic Link' field must fail loudly, not silently."""
    _install(jira, monkeypatch, CATALOG_WITHOUT_EPIC)
    with pytest.raises(ValueError) as exc:
        jira.jira_create(summary="hi", epic_link="TEST-100")
    assert "Epic Link" in str(exc.value)


def test_epic_link_empty_is_noop(jira, monkeypatch):
    cap = _install(jira, monkeypatch, CATALOG_WITH_EPIC)
    jira.jira_create(summary="hi")
    _, payload = cap["posts"][-1]
    assert "customfield_10001" not in payload["fields"]
