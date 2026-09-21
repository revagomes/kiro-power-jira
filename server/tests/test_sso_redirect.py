"""Regression tests for SSO-gateway handling in ``_api_request``.

An interactive SSO reverse proxy (EU Login/ECAS, Okta, SiteMinder, etc.) answers
API calls with a 30x redirect to a login host, ending on a ``200 OK`` HTML page.
``json.loads`` on that HTML used to raise a raw ``JSONDecodeError``. These tests
lock in the current behaviour:

- a cross-host redirect surfaces as a clear ``JiraApiError``
- a same-host redirect is NOT over-blocked
- a ``200`` carrying non-JSON (HTML) surfaces as a clear ``JiraApiError``
- a well-formed ``application/json`` ``200`` is parsed and returned as before
- a ``200`` claiming JSON but with a malformed body fails legibly

All network access is mocked at the ``_OPENER`` / redirect-handler seam so no
live JIRA instance is required.
"""

import io
import urllib.request

import pytest


class _FakeResponse:
    """Minimal stand-in for an ``http.client.HTTPResponse`` context manager."""

    def __init__(self, body: bytes, content_type: str, url: str):
        self._body = body
        self.headers = {"Content-Type": content_type}
        self._url = url

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_opener(jira, monkeypatch, opener):
    """Swap the module-level ``_OPENER`` for a fake and reset field cache."""
    monkeypatch.setattr(jira, "_OPENER", opener)
    if hasattr(jira, "_reset_field_cache"):
        jira._reset_field_cache()


# ── cross-host redirect → clear error ─────────────────────────────────────────
def test_cross_host_redirect_raises_jira_api_error(jira, monkeypatch):
    """A redirect leaving the JIRA host is refused with an actionable message."""

    class _RedirectingOpener:
        def open(self, req, timeout=None):
            # Reproduce what _NoCrossHostRedirect.redirect_request does when the
            # SSO gateway bounces us to a different host.
            raise jira._SSORedirectError(
                "Request to JIRA was redirected to a different host "
                "('gw-sso-ip.tech.ec.europa.eu'). This instance appears to be "
                "behind an interactive SSO gateway that does not honor Personal "
                "Access Token auth. PAT-only access is not supported for this "
                "deployment."
            )

    _install_opener(jira, monkeypatch, _RedirectingOpener())

    with pytest.raises(jira.JiraApiError) as exc:
        jira._api_request("https://jira.example.com/rest/api/2/serverInfo")

    assert "redirected to a different host" in str(exc.value)
    assert exc.value.status is None


def test_redirect_handler_blocks_cross_host_hop(jira):
    """The redirect handler itself refuses the first cross-host hop."""
    handler = jira._NoCrossHostRedirect()
    req = urllib.request.Request("https://jira.example.com/rest/api/2/serverInfo")
    with pytest.raises(jira._SSORedirectError) as exc:
        handler.redirect_request(
            req,
            io.BytesIO(b""),
            302,
            "Found",
            {},
            "https://ecas.ec.europa.eu/cas/login?SAMLRequest=abc",
        )
    assert "ecas.ec.europa.eu" in str(exc.value)


def test_redirect_handler_allows_same_host_hop(jira):
    """A same-host redirect is delegated to urllib and NOT over-blocked."""
    handler = jira._NoCrossHostRedirect()
    req = urllib.request.Request("https://jira.example.com/rest/api/2/issue/TEST-1")
    # Same host, different path (e.g. trailing-slash normalisation). Should not
    # raise _SSORedirectError; urllib builds a new Request for the same host.
    new_req = handler.redirect_request(
        req,
        io.BytesIO(b""),
        302,
        "Found",
        {},
        "https://jira.example.com/rest/api/2/issue/TEST-1/",
    )
    assert new_req is not None
    assert "jira.example.com" in new_req.full_url


# ── non-JSON 200 → clear error ────────────────────────────────────────────────
def test_html_body_raises_content_type_error(jira, monkeypatch):
    """A 200 carrying an HTML login page fails with a content-type message."""

    class _HtmlOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(
                b"<html><body>Please log in</body></html>",
                "text/html; charset=UTF-8",
                "https://ecas.ec.europa.eu/cas/login",
            )

    _install_opener(jira, monkeypatch, _HtmlOpener())

    with pytest.raises(jira.JiraApiError) as exc:
        jira._api_request("https://jira.example.com/rest/api/2/serverInfo")

    msg = str(exc.value)
    assert "text/html" in msg
    assert "ecas.ec.europa.eu" in msg
    assert exc.value.status is None


def test_missing_content_type_raises(jira, monkeypatch):
    """An empty/absent Content-Type on a non-empty body is treated as non-JSON."""

    class _NoCtypeOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(b"surprise", "", "https://jira.example.com/x")

    _install_opener(jira, monkeypatch, _NoCtypeOpener())

    with pytest.raises(jira.JiraApiError) as exc:
        jira._api_request("https://jira.example.com/rest/api/2/serverInfo")
    assert "unknown content type" in str(exc.value)


def test_malformed_json_body_raises_legibly(jira, monkeypatch):
    """A 200 claiming JSON but with a bad body fails with a clear message."""

    class _BadJsonOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(
                b"not really json",
                "application/json",
                "https://jira.example.com/x",
            )

    _install_opener(jira, monkeypatch, _BadJsonOpener())

    with pytest.raises(jira.JiraApiError) as exc:
        jira._api_request("https://jira.example.com/rest/api/2/serverInfo")
    assert "non-JSON response" in str(exc.value)


# ── happy path preserved ──────────────────────────────────────────────────────
def test_valid_json_response_is_parsed(jira, monkeypatch):
    """A well-formed application/json 200 is parsed and returned unchanged."""

    class _JsonOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(
                b'{"key": "TEST-1", "id": "42"}',
                "application/json;charset=UTF-8",
                "https://jira.example.com/rest/api/2/issue/TEST-1",
            )

    _install_opener(jira, monkeypatch, _JsonOpener())

    result = jira._api_request("https://jira.example.com/rest/api/2/issue/TEST-1")
    assert result == {"key": "TEST-1", "id": "42"}


def test_empty_body_returns_empty_dict(jira, monkeypatch):
    """A 200 with no body returns {} (e.g. 204-style PUT/DELETE responses)."""

    class _EmptyOpener:
        def open(self, req, timeout=None):
            return _FakeResponse(b"", "application/json", "https://jira.example.com/x")

    _install_opener(jira, monkeypatch, _EmptyOpener())

    assert jira._api_request("https://jira.example.com/x", method="DELETE") == {}
