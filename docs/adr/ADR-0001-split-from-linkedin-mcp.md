# ADR-0001: Split Company Page tools into linkedin-corp-mcp

## Context

LinkedIn personal member APIs (Share on LinkedIn, `w_member_social`) and
organization APIs (Community Management, `w_organization_social`) differ in:

- OAuth scopes and consent UX
- LinkedIn product approval path (consumer vs partner)
- Author URN type (`urn:li:person` vs `urn:li:organization`)
- Operational blast radius

Initial `linkedin-mcp` v1 intentionally scoped to personal accounts only.

## Decision

Implement Company Page tools in a **separate** MCP server:

- Folder: `mcp/linkedin-corp-mcp/`
- Registry id: `mcpServer=linkedin-corp`
- Do **not** extend `linkedin-mcp` with org scopes or org posting tools.

## Alternatives considered

1. **Single server with scope profiles** — rejected: mixed consent, harder security review, larger default attack surface.
2. **Upgrade linkedin-mcp in place** — rejected per product direction: keeps personal server lean and shippable without partner gates.

## Consequences

- Two deployable units in `mcp-tools` namespace when both are needed.
- Operators may reuse the same LinkedIn app credentials but must OAuth with org scopes separately.
- Documentation and registry must reference both servers explicitly.

## Risks

- LinkedIn may deny org API access until partner approval — server fails at runtime with `PERMISSION_DENIED`; document prerequisite clearly.
