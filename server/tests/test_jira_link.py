"""Tests for jira_link unknown-type handling (spec change #1)."""

import pytest


def _make_recorder(jira, *, fail_on_post=False):
    """Build a fake _api_request that records calls and can simulate a bad type.

    Returns (calls, fn). ``calls`` is a list of (method, url, payload) tuples.
    When ``fail_on_post`` is True, POSTs to /issueLink raise the structured 404
    that JIRA returns for an unknown link type; GETs to /issueLinkType return a
    catalog.
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
                raise jira.JiraApiError(
                    "No issue link type with name 'Relates' found.", status=404
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
        jira.jira_link("TEST-1", "TEST-2", link_type="Depends")

    msg = str(exc.value)
    # Must name the offending type and list the valid ones from this instance.
    assert "Depends" in msg
    assert "Related" in msg
    assert "Blocks" in msg
    # Must have consulted the issueLinkType catalog.
    assert any(u.endswith("/issueLinkType") for _, u, _ in calls)


def _catalog_recorder(jira, names):
    """Fake whose instance only knows ``names``; POSTs with other types 404."""
    calls = []

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if url.endswith("/issueLinkType") and method == "GET":
            return {"issueLinkTypes": [{"id": str(i), "name": n} for i, n in enumerate(names)]}
        if url.endswith("/issueLink") and method == "POST":
            if payload["type"]["name"] not in names:
                raise jira.JiraApiError("No issue link type found.", status=404)
            return {}
        return {}

    return calls, fake


def test_link_default_relates_falls_back_to_related(jira, monkeypatch):
    """Instances that call the standard type "Related" still link with the default."""
    calls, fake = _catalog_recorder(jira, ["Related", "Blocks"])
    monkeypatch.setattr(jira, "_api_request", fake)

    result = jira.jira_link("TEST-1", "TEST-2")

    posts = [c[2]["type"]["name"] for c in calls if c[0] == "POST"]
    assert posts == ["Relates", "Related"]
    assert result["linked"] == "TEST-1 --[Related]--> TEST-2"


def test_link_relates_fallback_matches_case_insensitively(jira, monkeypatch):
    calls, fake = _catalog_recorder(jira, ["relation", "Blocks"])
    monkeypatch.setattr(jira, "_api_request", fake)

    result = jira.jira_link("TEST-1", "TEST-2", link_type="Relates")

    assert "--[relation]-->" in result["linked"]


def test_link_relates_without_equivalent_raises_with_valid_names(jira, monkeypatch):
    calls, fake = _catalog_recorder(jira, ["Blocks", "Duplicate"])
    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(ValueError) as exc:
        jira.jira_link("TEST-1", "TEST-2")

    msg = str(exc.value)
    assert "Relates" in msg and "Blocks" in msg and "Duplicate" in msg
    # Only the original attempt was posted: no blind retries.
    assert [c[2]["type"]["name"] for c in calls if c[0] == "POST"] == ["Relates"]


def test_link_other_unknown_type_is_not_remapped(jira, monkeypatch):
    """Only the "relates" family falls back; other names keep the clear error."""
    calls, fake = _catalog_recorder(jira, ["Related", "Blocking"])
    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(ValueError):
        jira.jira_link("TEST-1", "TEST-2", link_type="Blocks")
    assert [c[2]["type"]["name"] for c in calls if c[0] == "POST"] == ["Blocks"]


def test_link_unknown_type_when_catalog_lookup_also_fails(jira, monkeypatch):
    """If the issueLinkType lookup also fails, still raise a clear (if listless) error."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/issueLinkType") and method == "GET":
            raise jira.JiraApiError("boom", status=500)
        if url.endswith("/issueLink") and method == "POST":
            raise jira.JiraApiError("unknown type", status=404)
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
            raise jira.JiraApiError("unknown type", status=404)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(ValueError) as exc:
        jira.jira_link("TEST-1", "TEST-2", link_type="Nope")
    assert "Nope" in str(exc.value)


def test_link_unknown_type_does_not_swallow_other_errors(jira, monkeypatch):
    """A non-link-type failure (e.g. permission) must not be masked as a bad type."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/issueLink") and method == "POST":
            raise jira.JiraApiError("permission denied", status=403)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(jira.JiraApiError) as exc:
        jira.jira_link("TEST-1", "TEST-2", link_type="Related")
    assert exc.value.status == 403


def test_link_does_not_misclassify_400_error_that_mentions_404(jira, monkeypatch):
    """A non-404 error whose message text contains '404' (e.g. a ticket key) must
    NOT be treated as an unknown link type."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/issueLink") and method == "POST":
            # e.g. a 400 whose message echoes a ticket like PROJ-404
            raise jira.JiraApiError(
                "Issue PROJ-404 does not exist", status=400
            )
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(jira.JiraApiError) as exc:
        jira.jira_link("TEST-1", "TEST-2", link_type="Related")
    # Must surface the real 400, not a bogus "unknown link type" ValueError.
    assert exc.value.status == 400


def test_link_404_with_known_type_is_reraised_not_called_unknown(jira, monkeypatch):
    """A 404 for a type the instance has means a missing issue, not a bad type."""
    def fake(url, method="GET", payload=None):
        if url.endswith("/issueLinkType") and method == "GET":
            return {"issueLinkTypes": [{"id": "1", "name": "Relates"}]}
        if url.endswith("/issueLink") and method == "POST":
            raise jira.JiraApiError("Issue Does Not Exist", status=404)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(jira.JiraApiError) as exc:
        jira.jira_link("TEST-1", "TEST-9999")
    assert exc.value.status == 404


def test_link_fallback_retry_failure_propagates_once(jira, monkeypatch):
    """If the retry with the equivalent type also fails, its error surfaces; no loop."""
    calls = []

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if url.endswith("/issueLinkType") and method == "GET":
            return {"issueLinkTypes": [{"id": "1", "name": "Related"}]}
        if url.endswith("/issueLink") and method == "POST":
            raise jira.JiraApiError("Issue Does Not Exist", status=404)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(jira.JiraApiError):
        jira.jira_link("TEST-1", "TEST-9999")
    assert [c[2]["type"]["name"] for c in calls if c[0] == "POST"] == ["Relates", "Related"]


def test_link_wrong_case_type_is_retried_with_the_instance_spelling(jira, monkeypatch):
    """A type given in the wrong case is retried once with the instance's spelling."""
    calls, fake = _catalog_recorder(jira, ["Related", "Blocks"])
    monkeypatch.setattr(jira, "_api_request", fake)
    # Make the first POST fail as a type 404 (the fake only accepts exact names).
    result = jira.jira_link("TEST-1", "TEST-2", link_type="related")

    posts = [c[2]["type"]["name"] for c in calls if c[0] == "POST"]
    assert posts == ["related", "Related"]
    assert result["linked"] == "TEST-1 --[Related]--> TEST-2"


def test_link_wrong_case_type_with_missing_ticket_raises_the_real_error(jira, monkeypatch):
    """The type exists (ignoring case): a 404 on the retry is about the issue."""
    calls = []

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if url.endswith("/issueLinkType") and method == "GET":
            return {"issueLinkTypes": [{"id": "1", "name": "Related"}]}
        if url.endswith("/issueLink") and method == "POST":
            raise jira.JiraApiError("Issue Does Not Exist", status=404)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(jira.JiraApiError) as exc:
        jira.jira_link("TEST-1", "TEST-9999", link_type="related")
    assert exc.value.status == 404
    assert [c[2]["type"]["name"] for c in calls if c[0] == "POST"] == ["related", "Related"]
