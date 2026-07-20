# LinkedIn Corp MCP Server

MCP tool-server for **LinkedIn Company Page** (organization) operations.

Personal member posting lives in sibling [`../linkedin-mcp/`](../linkedin-mcp/) (`mcpServer=linkedin`).

## Prerequisites

1. LinkedIn Developer app with **Community Management** / **Marketing Developer Platform** access (partner approval often required).
2. OAuth scopes: `openid profile email r_organization_social w_organization_social rw_organization_admin`.
3. Authenticated user must be a **Page administrator** for target organizations.

## Quick start

```bash
cd mcp/linkedin-corp-mcp
cp .env.example .env
# Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET

python -m venv .venv && source .venv/bin/activate
pip install -r requirements_mcp.txt

# Optional: local OAuth connect (port 8766 to avoid clash with linkedin-mcp)
python scripts/oauth_connect.py

# Run HTTP server (use 8001 if linkedin-mcp uses 8000)
LINKEDIN_CORP_ENABLE_OAUTH_UI=1 uvicorn app.mcp_server:http_app --host 0.0.0.0 --port 8001
```

Test UI: `http://127.0.0.1:8001/test` (when `LINKEDIN_CORP_ENABLE_OAUTH_UI=1`).

## Tools

| Tool | Description |
|------|-------------|
| `get_me` | Authenticated member profile (operator context) |
| `list_my_organizations` | Company Pages you administer |
| `get_organization` | Org metadata by id or vanity name |
| `create_organization_post` | Text/article post as org (`confirm=true`) |
| `create_organization_image_post` | Image post as org (`confirm=true`) |
| `get_organization_post` | Fetch post by URN |
| `delete_organization_post` | Delete post (`confirm=true`) |

## Registry

- **MCP server id:** `linkedin-corp`
- **In-cluster URL:** `http://linkedin-corp-mcp-main.mcp-tools.svc.cluster.local:8000/mcp/`

## Kubernetes

```bash
cp .env.example .env
./k8s-deploy.sh
```

## Tests

```bash
python scripts/test_helpers.py
```

## Documentation

- [`design.md`](design.md) — architecture and scope
- [`docs/operations/manual-testing.md`](docs/operations/manual-testing.md) — manual test checklist
- [`docs/adr/ADR-0001-split-from-linkedin-mcp.md`](docs/adr/ADR-0001-split-from-linkedin-mcp.md)
