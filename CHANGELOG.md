# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-16

### Added
- Runtime custom-field resolution: field names are resolved to their
  instance-specific ids at runtime (cached for the process lifetime), so no
  field id is hardcoded.
- `custom_fields` parameter on `jira_create` and `jira_update` — set any
  instance-specific field by human name or raw id, with typed parameters
  taking precedence on collision.
- `epic_link` and `story_points` convenience parameters on `jira_create` and
  `jira_update`, resolved by field name at runtime.
- `jira_view` now returns the ticket's epic link for read-back.
- Version-management tools: `jira_create_version`, `jira_list_versions`,
  `jira_release_version`, `jira_update_version`, `jira_delete_version`
  (with start-date support on list/update).
- Offline test suite (pytest) covering the field-coverage behavior and
  security invariants; no network access required.

### Changed
- `jira_link` now reports the instance's valid link-type names when an unknown
  link type is supplied, instead of surfacing a raw HTTP error.
- API errors are raised with the HTTP status attached, so callers can branch on
  the status precisely rather than parsing the message.
- Documentation updated to reflect the full set of 24 MCP tools.

### Security
- Lagune security review pass over the new code; controls verified and locked
  in with regression tests (custom-field values stay in the request body, and
  only shaped, catalog-sourced field ids reach read URLs).

## [0.3.0] - 2026-08-12

### Added
- Lagune security framework: charter, detect map, defense plan, and hardening
  record.

### Security
- Enforced HTTPS on outbound requests, sanitized error responses, added JQL
  validation, and applied proper URL encoding for path and query segments.

## [0.2.0] - 2026-08-12

### Added
- Robust `.env` loader supporting the `export` prefix, balanced quoting, and
  inline comments.

### Fixed
- `_check_config` now validates the module-level configuration constants rather
  than live environment variables, keeping configuration checks self-consistent.

## [0.1.0] - 2026-08-12

### Added
- Initial release of the JIRA Kiro Power: a self-contained FastMCP server
  exposing JIRA ticket, search, transition, comment, link, board, and sprint
  operations over the REST API v2, configured entirely via environment
  variables.

[0.4.0]: https://github.com/revagomes/kiro-power-jira/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/revagomes/kiro-power-jira/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/revagomes/kiro-power-jira/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/revagomes/kiro-power-jira/releases/tag/v0.1.0
