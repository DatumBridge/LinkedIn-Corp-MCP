# Design: LinkedIn Corp MCP Server

## Class

**Python FastMCP tool-server** for LinkedIn **Company Page / organization** operations.
Sibling to `linkedin-mcp` (personal member account). Do not merge org tools into
`linkedin-mcp` — different OAuth scopes, API products, and blast radius.

## Purpose

Expose LinkedIn organization social operations as MCP tools for DatumBridge
workflows that post as Company Pages.

## Architecture

```text
Caller → Streamable HTTP /mcp → FastMCP tools → LinkedInCorpService → LinkedIn REST (v2)
                 ↑
         OAuth credentials per call (org scopes)
```

## Key decisions

1. **Separate server** — registry id `mcpServer=linkedin-corp`, not `linkedin`.
2. **Org OAuth scopes** — `r_organization_social`, `w_organization_social`, `rw_organization_admin` (+ OIDC).
3. **Author binding** — posts must use `urn:li:organization:<id>` from `list_my_organizations`.
4. **Pass-through OAuth** — same credential pattern as `linkedin-mcp`.
5. **Confirm / dry_run gates** — create and delete require `confirm=true`.
6. **Default visibility PUBLIC** — typical for Company Page posts.
7. **Prerequisite** — LinkedIn Community Management / Marketing Developer Platform approval.

## v1 tools

| Tool | Purpose |
|------|---------|
| `get_me` | Operator identity (OpenID userinfo) |
| `list_my_organizations` | Company Pages the member administers |
| `get_organization` | Org metadata by id or vanity name |
| `create_organization_post` | Text/article share as organization |
| `create_organization_image_post` | Image share as organization |
| `get_organization_post` | Fetch UGC post by URN |
| `delete_organization_post` | Delete UGC post by URN |

## Non-goals (v1)

- Personal member posting (use `linkedin-mcp`)
- Ads, analytics, lead gen
- Comments / reactions
- Messaging / InMail

## Platform contracts

- `GET /health`
- `POST /mcp/` Streamable HTTP
- Registry: `mcpServer=linkedin-corp`

See `docs/adr/ADR-0001-split-from-linkedin-mcp.md`.
