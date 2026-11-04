"""Tests for jira_change_issue_type (EJPREV-4143).

Covers:
  - the happy path (PUT /issue/{key} with an issuetype field)
  - invalid target type -> ValueError listing the project's valid types
    (mirroring jira_link's unknown-link-type handling)
  - a non-type failure (e.g. permission) is not masked as an invalid type
  - read-back of the new type via a follow-up GET
  - ticket-key validation
"""

import pytest


def _make_recorder(
    jira,
    *,
    fail_put_status=None,
    project_types=("Bug", "Task", "Story", "Epic", "Improvement"),
    readback_type="Bug",
):
    """Build a fake _api_request that records calls.

    - GET /project/{key} returns an issueTypes catalog built from
      ``project_types``.
    - GET /issue/{key} (read-back) returns an issue whose type is
      ``readback_type``.
    - PUT /issue/{key} succeeds unless ``fail_put_status`` is set, in which case
      it raises a structured JiraApiError with that status.
    """
    calls = []

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if "/project/" in url and method == "GET":
            return {
                "id": "10000",
                "key": "TEST",
                "issueTypes": [
                    {"id": str(i), "name": n, "subtask": False}
                    for i, n in enumerate(project_types, start=1)
                ],
            }
        if "/issue/" in url and method == "PUT":
            if fail_put_status is not None:
                raise jira.JiraApiError(
                    "Some message from JIRA", status=fail_put_status
                )
            return {}
        if "/issue/" in url and method == "GET":
            return {
                "key": "TEST-1",
                "fields": {"issuetype": {"name": readback_type}},
            }
        return {}

    return calls, fake


def test_change_type_success_puts_expected_payload(jira, monkeypatch):
    # Read-back returns a DIFFERENT type than requested so the test proves the
    # returned value comes from JIRA's authoritative read-back, not an echo of
    # the request.
    calls, fake = _make_recorder(jira, readback_type="Story")
    monkeypatch.setattr(jira, "_api_request", fake)

    result = jira.jira_change_issue_type("TEST-1", "Bug")

    puts = [c for c in calls if c[0] == "PUT"]
    assert len(puts) == 1
    _, url, payload = puts[0]
    assert url.endswith("/issue/TEST-1")
    assert payload["fields"]["issuetype"]["name"] == "Bug"
    # Read-back GET must request the issuetype field explicitly.
    gets = [c for c in calls if c[0] == "GET" and "/issue/" in c[1]]
    assert len(gets) == 1
    assert "fields=issuetype" in gets[0][1]
    assert result["ticket"] == "TEST-1"
    # Authoritative read-back value, not the requested "Bug".
    assert result["issue_type"] == "Story"


def test_change_type_invalid_raises_with_valid_types(jira, monkeypatch):
    # JIRA returns 400 when the target type is not valid for the issue/screen.
    calls, fake = _make_recorder(
        jira, fail_put_status=400, project_types=("Bug", "Task", "Epic")
    )
    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(ValueError) as exc:
        jira.jira_change_issue_type("TEST-1", "Nonsense")

    msg = str(exc.value)
    assert "Nonsense" in msg
    # Must list the project's valid issue types.
    assert "Bug" in msg and "Task" in msg and "Epic" in msg
    # Must have consulted the project issue-type catalog.
    assert any("/project/" in u for _, u, _ in calls)


def test_change_type_does_not_swallow_permission_error(jira, monkeypatch):
    # A 403 must surface as-is, not be reinterpreted as a bad type.
    _calls, fake = _make_recorder(jira, fail_put_status=403)
    monkeypatch.setattr(jira, "_api_request", fake)

    with pytest.raises(jira.JiraApiError) as exc:
        jira.jira_change_issue_type("TEST-1", "Bug")
    assert exc.value.status == 403
    # Non-400s must short-circuit BEFORE the catalog is consulted.
    assert not any("/project/" in u for _, u, _ in _calls)


def test_change_type_rejects_invalid_key(jira, monkeypatch):
    _calls, fake = _make_recorder(jira)
    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(ValueError):
        jira.jira_change_issue_type("not-a-key", "Bug")


def test_change_type_requires_target_type(jira, monkeypatch):
    _calls, fake = _make_recorder(jira)
    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(ValueError):
        jira.jira_change_issue_type("TEST-1", "   ")


def test_change_type_invalid_when_catalog_also_fails(jira, monkeypatch):
    """If the project catalog lookup also fails, still raise a clear error."""
    def fake(url, method="GET", payload=None):
        if "/project/" in url and method == "GET":
            raise jira.JiraApiError("boom", status=500)
        if "/issue/" in url and method == "PUT":
            raise jira.JiraApiError("bad type", status=400)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(ValueError) as exc:
        jira.jira_change_issue_type("TEST-1", "Whatever")
    assert "Whatever" in str(exc.value)


def test_change_type_invalid_when_catalog_malformed(jira, monkeypatch):
    """A non-dict project response degrades to an empty valid-types list."""
    def fake(url, method="GET", payload=None):
        if "/project/" in url and method == "GET":
            return []  # unexpected shape (list, not dict)
        if "/issue/" in url and method == "PUT":
            raise jira.JiraApiError("bad type", status=400)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    with pytest.raises(ValueError) as exc:
        jira.jira_change_issue_type("TEST-1", "Nope")
    msg = str(exc.value)
    assert "Nope" in msg
    # An empty/unknown catalog degrades to the explicit fallback string.
    assert "(none returned by the instance)" in msg


def test_change_type_readback_failure_falls_back_to_requested(jira, monkeypatch):
    """If the read-back GET fails, the requested type is echoed, not an error."""
    def fake(url, method="GET", payload=None):
        if "/issue/" in url and method == "PUT":
            return {}
        if "/issue/" in url and method == "GET":
            raise jira.JiraApiError("read-back failed", status=500)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    result = jira.jira_change_issue_type("TEST-1", "Bug")
    assert result == {"ticket": "TEST-1", "issue_type": "Bug"}
