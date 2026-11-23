"""Tests for jira_web_link, jira_web_links and jira_delete_comment."""

import pytest


def _install(jira, monkeypatch, *, existing=None):
    """Replace _api_request with a recorder.

    ``existing`` is the list returned by GET /issue/{key}/remotelink.
    Returns the list of recorded (method, url, payload) tuples.
    """
    calls = []

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if url.endswith("/remotelink") and method == "GET":
            return existing or []
        if url.endswith("/remotelink") and method == "POST":
            return {"id": 10042, "self": url + "/10042"}
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)
    return calls


# ── jira_web_link ─────────────────────────────────────────────────────────────
def test_web_link_posts_url_and_title(jira, monkeypatch):
    calls = _install(jira, monkeypatch)

    result = jira.jira_web_link(
        "test-1", "https://gitlab.example.com/mr/942", "MR !942"
    )

    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1
    method, url, payload = posts[0]
    assert url == "https://jira.example.com/rest/api/2/issue/TEST-1/remotelink"
    assert payload == {
        "object": {"url": "https://gitlab.example.com/mr/942", "title": "MR !942"}
    }
    assert result == {
        "ticket": "TEST-1",
        "link_id": "10042",
        "url": "https://gitlab.example.com/mr/942",
        "title": "MR !942",
        "created": True,
    }


def test_web_link_includes_summary_when_given(jira, monkeypatch):
    calls = _install(jira, monkeypatch)

    jira.jira_web_link(
        "TEST-1", "https://x.example.com/a", "A", summary="Restore history"
    )

    payload = [c for c in calls if c[0] == "POST"][0][2]
    assert payload["object"]["summary"] == "Restore history"


def test_web_link_title_defaults_to_url(jira, monkeypatch):
    calls = _install(jira, monkeypatch)

    result = jira.jira_web_link("TEST-1", "https://x.example.com/a")

    assert result["title"] == "https://x.example.com/a"
    assert [c for c in calls if c[0] == "POST"][0][2]["object"]["title"] == (
        "https://x.example.com/a"
    )


def test_web_link_is_idempotent_for_an_existing_url(jira, monkeypatch):
    existing = [
        {"id": 7, "object": {"url": "https://x.example.com/a", "title": "Old"}}
    ]
    calls = _install(jira, monkeypatch, existing=existing)

    result = jira.jira_web_link("TEST-1", "https://x.example.com/a", "New")

    assert not [c for c in calls if c[0] == "POST"]
    assert result["created"] is False
    assert result["link_id"] == "7"
    assert result["title"] == "Old"


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://x.example.com/a",
        "x.example.com/no-scheme",
        "https://",
        "",
        "https://x.example.com/a\nb",
    ],
)
def test_web_link_rejects_unsafe_urls(jira, monkeypatch, bad_url):
    calls = _install(jira, monkeypatch)

    with pytest.raises(ValueError):
        jira.jira_web_link("TEST-1", bad_url, "t")

    assert calls == []


def test_web_link_rejects_invalid_ticket_key(jira, monkeypatch):
    calls = _install(jira, monkeypatch)

    with pytest.raises(ValueError):
        jira.jira_web_link("not a key", "https://x.example.com/a", "t")

    assert calls == []


# ── jira_web_links ────────────────────────────────────────────────────────────
def test_web_links_lists_existing_links(jira, monkeypatch):
    existing = [
        {"id": 7, "object": {"url": "https://x.example.com/a", "title": "A"}},
        {"id": 8, "object": {"url": "https://x.example.com/b"}},
    ]
    calls = _install(jira, monkeypatch, existing=existing)

    result = jira.jira_web_links("TEST-1")

    assert calls[0][:2] == (
        "GET",
        "https://jira.example.com/rest/api/2/issue/TEST-1/remotelink",
    )
    assert result == [
        {"link_id": "7", "url": "https://x.example.com/a", "title": "A"},
        {"link_id": "8", "url": "https://x.example.com/b", "title": ""},
    ]


# ── jira_delete_comment ───────────────────────────────────────────────────────
def test_delete_comment_issues_delete_on_the_comment_path(jira, monkeypatch):
    calls = _install(jira, monkeypatch)

    result = jira.jira_delete_comment("test-1", "9568584")

    assert calls == [
        (
            "DELETE",
            "https://jira.example.com/rest/api/2/issue/TEST-1/comment/9568584",
            None,
        )
    ]
    assert result == {"ticket": "TEST-1", "deleted_comment_id": "9568584"}


@pytest.mark.parametrize("bad_id", ["", "abc", "12/../34", "1 2", "12?x=1"])
def test_delete_comment_rejects_non_numeric_ids(jira, monkeypatch, bad_id):
    calls = _install(jira, monkeypatch)

    with pytest.raises(ValueError):
        jira.jira_delete_comment("TEST-1", bad_id)

    assert calls == []


def test_delete_comment_rejects_invalid_ticket_key(jira, monkeypatch):
    calls = _install(jira, monkeypatch)

    with pytest.raises(ValueError):
        jira.jira_delete_comment("nope", "123")

    assert calls == []
