"""Security-invariant regression tests locking in the Lagune defense plan.

These guard controls that already hold in the code; each fails if a future
change breaks the invariant the plan requires.

Traceability (findings from .lagune/memory/plan.md):
- "Arbitrary custom-field write via custom_fields": a custom-field value must
  reach JIRA only in the request JSON body, never interpolated into a URL.
- "Field name resolved against the instance catalog and used in a read URL":
  only a catalog-sourced, customfield_\\d+-shaped id may enter jira_view's URL.
"""

import re

import pytest

CATALOG = [
    {"id": "customfield_10001", "name": "Epic Link", "custom": True},
    {"id": "customfield_10004", "name": "Story Points", "custom": True},
]

_CUSTOMFIELD_ID_RE = re.compile(r"^customfield_\d+$")

# A distinctive value we can search for across every recorded URL.
_SENTINEL = "SENTINEL_VALUE_1234567890"


def _install(jira, monkeypatch):
    """Record every (method, url, payload) so we can assert where values land."""
    calls = []

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if url.endswith("/field") and method == "GET":
            return CATALOG
        if "/issue/" in url and method == "GET":
            return {"key": "TEST-1", "fields": {"customfield_10001": "TEST-9"}}
        if method == "POST":
            return {"key": "TEST-1"}
        if method == "PUT":
            return {}
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    jira._reset_field_cache()
    return calls


def test_custom_field_value_never_enters_a_url_on_create(jira, monkeypatch):
    calls = _install(jira, monkeypatch)
    jira.jira_create(
        summary="hi", custom_fields={"customfield_10004": _SENTINEL}
    )
    # The sentinel must never appear in any URL...
    for _method, url, _payload in calls:
        assert _SENTINEL not in url, f"value leaked into URL: {url}"
    # ...and must be present in a POST body.
    post_bodies = [p for m, _, p in calls if m == "POST"]
    assert any(_SENTINEL in str(p) for p in post_bodies)


def test_custom_field_value_never_enters_a_url_on_update(jira, monkeypatch):
    calls = _install(jira, monkeypatch)
    jira.jira_update("TEST-1", custom_fields={"customfield_10004": _SENTINEL})
    for _, url, _payload in calls:
        assert _SENTINEL not in url, f"value leaked into URL: {url}"
    # And it must be present in a PUT body.
    put_bodies = [p for m, _, p in calls if m == "PUT"]
    assert any(_SENTINEL in str(p) for p in put_bodies)


def test_jira_view_only_puts_a_shaped_field_id_in_the_url(jira, monkeypatch):
    calls = _install(jira, monkeypatch)
    jira.jira_view("TEST-1")
    issue_gets = [u for m, u, _ in calls if m == "GET" and "/issue/" in u]
    assert issue_gets, "expected an issue GET"
    url = issue_gets[-1]
    # Extract the fields= query and confirm every non-standard token that looks
    # like a custom field id matches the customfield_\d+ shape.
    assert "fields=" in url
    fields_part = url.split("fields=", 1)[1].split("&", 1)[0]
    for token in fields_part.split(","):
        if token.startswith("customfield"):
            assert _CUSTOMFIELD_ID_RE.match(token), (
                f"unshaped custom field id in URL: {token!r}"
            )
