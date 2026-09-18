"""Tests for story_points param and epic-link read-back in jira_view (change #4)."""

import pytest

CATALOG = [
    {"id": "customfield_10001", "name": "Epic Link", "custom": True},
    {"id": "customfield_10004", "name": "Story Points", "custom": True},
]


def _install(jira, monkeypatch, *, issue_fields=None):
    captured = {"posts": [], "puts": [], "gets": []}

    def fake(url, method="GET", payload=None):
        if url.endswith("/field") and method == "GET":
            return CATALOG
        if "/issue/" in url and method == "GET":
            captured["gets"].append(url)
            return {
                "key": "TEST-1",
                "fields": issue_fields or {},
            }
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


# ── story_points ────────────────────────────────────────────────────────────

def test_create_with_story_points(jira, monkeypatch):
    cap = _install(jira, monkeypatch)
    jira.jira_create(summary="hi", story_points=5)
    _, payload = cap["posts"][-1]
    assert payload["fields"]["customfield_10004"] == 5


def test_update_with_story_points(jira, monkeypatch):
    cap = _install(jira, monkeypatch)
    jira.jira_update("TEST-1", story_points=8)
    _, payload = cap["puts"][-1]
    assert payload["fields"]["customfield_10004"] == 8


def test_story_points_none_is_noop(jira, monkeypatch):
    cap = _install(jira, monkeypatch)
    jira.jira_create(summary="hi")
    _, payload = cap["posts"][-1]
    assert "customfield_10004" not in payload["fields"]


# ── epic-link read-back in jira_view ─────────────────────────────────────────

def test_view_surfaces_epic_link_when_present(jira, monkeypatch):
    issue_fields = {
        "summary": "A ticket",
        "customfield_10001": "TEST-100",
    }
    _install(jira, monkeypatch, issue_fields=issue_fields)
    result = jira.jira_view("TEST-1")
    assert result["epic_link"] == "TEST-100"


def test_view_epic_link_empty_when_absent(jira, monkeypatch):
    issue_fields = {"summary": "A ticket", "customfield_10001": None}
    _install(jira, monkeypatch, issue_fields=issue_fields)
    result = jira.jira_view("TEST-1")
    assert result["epic_link"] == ""


def test_view_still_works_when_epic_field_unresolvable(jira, monkeypatch):
    """If the instance has no Epic Link field, jira_view must not blow up."""
    captured = {"gets": []}

    def fake(url, method="GET", payload=None):
        if url.endswith("/field") and method == "GET":
            return [{"id": "customfield_10004", "name": "Story Points"}]
        if "/issue/" in url and method == "GET":
            captured["gets"].append(url)
            return {"key": "TEST-1", "fields": {"summary": "A ticket"}}
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    jira._reset_field_cache()
    result = jira.jira_view("TEST-1")
    assert result["summary"] == "A ticket"
    assert result["epic_link"] == ""


def test_view_requests_epic_field_when_resolvable(jira, monkeypatch):
    """When Epic Link resolves, its id is appended to the requested fields."""
    cap = _install(jira, monkeypatch, issue_fields={"summary": "x",
                                                    "customfield_10001": "TEST-9"})
    jira.jira_view("TEST-1")
    assert any("customfield_10001" in url for url in cap["gets"])


def test_story_points_unresolvable_raises_clear_error(jira, monkeypatch):
    """Instances without a 'Story Points' field must fail loudly on story_points."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/field") and method == "GET":
            return [{"id": "customfield_10001", "name": "Epic Link"}]
        if method == "POST":
            return {"key": "TEST-1"}
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    jira._reset_field_cache()
    with pytest.raises(ValueError) as exc:
        jira.jira_create(summary="hi", story_points=5)
    assert "Story Points" in str(exc.value)
