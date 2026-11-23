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
        "globalId": jira._web_link_global_id("https://gitlab.example.com/mr/942"),
        "object": {"url": "https://gitlab.example.com/mr/942", "title": "MR !942"},
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
        "https://:443/mr/42",
        "https://user@/mr/42",
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


def test_web_link_global_id_is_deterministic_per_url(jira):
    a = jira._web_link_global_id("https://x.example.com/a")

    assert a == jira._web_link_global_id("https://x.example.com/a")
    assert a != jira._web_link_global_id("https://x.example.com/b")


def test_overlapping_calls_send_the_same_global_id(jira, monkeypatch):
    """Two calls that both saw no link must hit JIRA's server-side upsert.

    The lookup and the create are separate requests, so overlapping calls can
    both find nothing. Both must carry the same globalId so JIRA creates the
    link once and updates it the second time instead of duplicating it.
    """
    calls = _install(jira, monkeypatch)

    jira.jira_web_link("TEST-1", "https://x.example.com/a", "A")
    jira.jira_web_link("TEST-1", "https://x.example.com/a", "A")

    global_ids = [c[2]["globalId"] for c in calls if c[0] == "POST"]
    assert len(global_ids) == 2
    assert global_ids[0] == global_ids[1]


def test_web_link_reports_update_when_jira_updated_instead_of_created(
    jira, monkeypatch
):
    """An upsert that updated an existing link returns no new id.

    A concurrent call created the link between our lookup and our POST, so JIRA
    updated it. We must report created=False and resolve the real link id.
    """
    calls = []
    lookups = iter([[], [{"id": 55, "object": {"url": "https://x.example.com/a", "title": "A"}}]])

    def fake(url, method="GET", payload=None):
        calls.append((method, url, payload))
        if method == "GET" and url.endswith("/remotelink"):
            return next(lookups)
        return {}

    monkeypatch.setattr(jira, "_api_request", fake)

    result = jira.jira_web_link("TEST-1", "https://x.example.com/a", "A")

    assert result["created"] is False
    assert result["link_id"] == "55"


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


@pytest.mark.parametrize(
    "bad_id", ["", "abc", "12/../34", "1 2", "12?x=1", "١٢٣", "12\n3"]
)
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
