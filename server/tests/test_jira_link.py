"""Tests for jira_link unknown-type handling (spec change #1)."""

import pytest


def _make_recorder(jira, *, fail_on_post=False):
    """Build a fake _api_request that records calls and can simulate a bad type.

    Returns (calls, fn). ``calls`` is a list of (method, url, payload) tuples.
    When ``fail_on_post`` is True, POSTs to /issueLink raise the 404 that JIRA
    returns for an unknown link type; GETs to /issueLinkType return a catalog.
    """
    calls = []

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if url.endswith("/issueLinkType") and method == "GET":
            return {
                "issueLinkTypes": [
                    {"id": "1", "name": "Related", "inward": "is related to",
                     "outward": "relates to"},
                    {"id": "2", "name": "Blocks", "inward": "is blocked by",
                     "outward": "blocks"},
                ]
            }
        if url.endswith("/issueLink") and method == "POST":
            if fail_on_post:
                raise RuntimeError(
                    "JIRA API error (404): No issue link type with name "
                    "'Relates' found."
                )
            return {}
        return {}

    return calls, fake


def test_link_success_posts_expected_payload(jira, monkeypatch):
    calls, fake = _make_recorder(jira, fail_on_post=False)
    monkeypatch.setattr(jira, "_api_request", fake)

    result = jira.jira_link("TEST-1", "TEST-2", link_type="Related")

    post = [c for c in calls if c[0] == "POST"]
    assert len(post) == 1
    _, url, payload = post[0]
    assert url.endswith("/issueLink")
    assert payload["type"]["name"] == "Related"
    assert payload["inwardIssue"]["key"] == "TEST-1"
    assert payload["outwardIssue"]["key"] == "TEST-2"
    assert "Related" in result["linked"]


def test_link_unknown_type_raises_with_valid_names(jira, monkeypatch):
    calls, fake = _make_recorder(jira, fail_on_post=True)
    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(ValueError) as exc:
        jira.jira_link("TEST-1", "TEST-2", link_type="Relates")

    msg = str(exc.value)
    # Must name the offending type and list the valid ones from this instance.
    assert "Relates" in msg
    assert "Related" in msg
    assert "Blocks" in msg
    # Must have consulted the issueLinkType catalog.
    assert any(u.endswith("/issueLinkType") for _, u, _ in calls)


def test_link_unknown_type_when_catalog_lookup_also_fails(jira, monkeypatch):
    """If the issueLinkType lookup also fails, still raise a clear (if listless) error."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/issueLinkType") and method == "GET":
            raise RuntimeError("JIRA API error (500): boom")
        if url.endswith("/issueLink") and method == "POST":
            raise RuntimeError("JIRA API error (404): unknown type")
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(ValueError) as exc:
        jira.jira_link("TEST-1", "TEST-2", link_type="Nope")
    assert "Nope" in str(exc.value)


def test_link_unknown_type_when_catalog_malformed(jira, monkeypatch):
    """A non-dict catalog response degrades to an empty valid-types list, no crash."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/issueLinkType") and method == "GET":
            return []  # unexpected shape (list, not dict)
        if url.endswith("/issueLink") and method == "POST":
            raise RuntimeError("JIRA API error (404): unknown type")
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(ValueError) as exc:
        jira.jira_link("TEST-1", "TEST-2", link_type="Nope")
    assert "Nope" in str(exc.value)


def test_link_unknown_type_does_not_swallow_other_errors(jira, monkeypatch):
    """A non-link-type failure (e.g. permission) must not be masked as a bad type."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/issueLink") and method == "POST":
            raise RuntimeError("JIRA API error (403): permission denied")
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(RuntimeError) as exc:
        jira.jira_link("TEST-1", "TEST-2", link_type="Related")
    assert "403" in str(exc.value)
