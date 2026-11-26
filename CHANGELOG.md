# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.1] - 2026-11-26

### Fixed
- `jira_link` with the default (or an explicit) `"Relates"` type now works on
  instances that name it differently: on the 404 it looks up the instance's
  equivalent (`Related`, `Relation`, `Relationship`, case-insensitive), retries
  once with it and reports the type used. Other unknown types still raise the
  error listing the valid names.
- `jira_link` retries once with the instance's spelling when the type differs
  only by case (e.g. `related` vs `Related`).
- `jira_link` no longer reports "Unknown link type" when the type exists and the
  404 is about the issues (e.g. a missing ticket); the original error is raised.

## [0.6.0] - 2026-11-23

### Added
- `jira_web_link` tool: add a web (remote) link, such as a merge request URL,
  to a ticket via `POST /issue/{key}/remotelink`. Only absolute http(s) URLs
  are accepted (no `javascript:`/`file:` schemes, no control characters). It is
  idempotent: a link with the same URL is not duplicated (the request carries a URL-derived globalId so JIRA upserts server-side) and the existing one is
  returned with `created: false`.
- `jira_web_links` tool: list a ticket's web links.
- `jira_delete_comment` tool: delete a comment by numeric id (the id returned by
  `jira_comment`); the id is ASCII-digits only so it cannot alter the request
  path, and nothing is deleted unless the caller passes `confirm=True`.
- `_api_request(..., return_status=True)` returns `(http_status, data)`;
  `jira_web_link` uses it to report `created: true` only for HTTP 201 (JIRA
  answers 200 with the existing id when it updates a link with the same
  `globalId`).

### Tests
- Offline tests for the three tools: payload and path shape, idempotency, URL
  scheme and control-character rejection, comment id validation, key validation.

### Documentation
- README and POWER tool tables updated to 28 tools; the "post the MR link" usage
  and the workflow steering now use `jira_web_link`.

## [0.5.0] - 2026-11-04

### Added
- `jira_change_issue_type` tool: change an existing ticket's issue type (e.g.
  Task → Bug) via `PUT /issue/{key}`. Invalid target types return a clear error
  listing the project's valid issue types instead of a raw HTTP 400 (mirroring
  `jira_link`'s unknown-link-type handling), and the new type is read back from
  JIRA and returned. Same-level retypes are applied directly; standard↔sub-task
  conversions are reported as requiring JIRA's Move wizard.

### Tests
- Offline tests for `jira_change_issue_type`: happy path and payload shape,
  invalid-type error listing valid types, permission (403) not masked as a bad
  type, key/empty-type validation, catalog-lookup failure and malformed-catalog
  degradation, and read-back-failure fallback.

### Documentation
- README and POWER tool tables updated to 25 tools; added a "Changing an
  issue's type" usage section.

## [0.4.1] - 2026-09-21

### Fixed
- JIRA instances behind an interactive SSO gateway (EU Login/ECAS, Okta,
  SiteMinder, etc.) now fail with a clear, actionable error instead of a raw
  `Expecting value: line 1 column 1 (char 0)` JSON parse error. `_api_request`
  refuses cross-host redirects, validates the response `Content-Type`, and
  guards `json.loads` so a login/HTML page served in front of JIRA is reported
  as such.

### Changed
- SSO/content-type failure paths now raise `JiraApiError` (with `status=None`)
  instead of a bare `RuntimeError`, keeping the API error contract uniform with
  the rest of `_api_request`.

### Tests
- Added offline regression tests for SSO redirect and content-type handling
  (cross-host redirect blocked, same-host redirect allowed, non-JSON body
  rejected, valid JSON still parsed).

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

[0.5.0]: https://github.com/revagomes/kiro-power-jira/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/revagomes/kiro-power-jira/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/revagomes/kiro-power-jira/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/revagomes/kiro-power-jira/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/revagomes/kiro-power-jira/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/revagomes/kiro-power-jira/releases/tag/v0.1.0
