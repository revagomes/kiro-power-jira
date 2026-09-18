"""Smoke tests: confirm the module imports and its callable surface is usable."""


def test_module_imports(jira):
    assert jira is not None
    assert jira.PROJECT == "TEST"
    assert jira.JIRA_BASE == "https://jira.example.com/rest/api/2"


def test_tool_callables_present(jira):
    # Discover how @mcp.tool()-decorated functions are exposed.
    for name in ("jira_create", "jira_update", "jira_link", "jira_view"):
        assert hasattr(jira, name), f"missing {name}"
