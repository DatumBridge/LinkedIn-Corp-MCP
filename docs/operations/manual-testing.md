# Manual testing — LinkedIn Corp MCP

## Prerequisites

- LinkedIn app with Community Management / org social products approved
- Page administrator role on at least one Company Page
- `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` in `.env`

## Local HTTP + Test UI

```bash
cp .env.example .env
# fill credentials

python -m venv .venv && source .venv/bin/activate
pip install -r requirements_mcp.txt

export LINKEDIN_CORP_ENABLE_OAUTH_UI=1
uvicorn app.mcp_server:http_app --host 0.0.0.0 --port 8001
```

1. Open `http://127.0.0.1:8001/test`
2. Connect OAuth (org scopes)
3. Run tools in order:
   - `get_me`
   - `list_my_organizations`
   - `get_organization` (use id or vanity from list)
   - `create_organization_post` with `dry_run=true`, then `confirm=true`
   - `get_organization_post` with returned URN
   - `delete_organization_post` with `confirm=true` (optional cleanup)

## OAuth CLI

```bash
python scripts/oauth_connect.py
# writes token.json — pass as credentials_path
```

Add redirect URL from script output to LinkedIn Developer Portal.

## Kubernetes

```bash
./k8s-deploy.sh
kubectl -n mcp-tools get svc linkedin-corp-mcp-main
# Test UI: http://127.0.0.1:<NodePort>/test
```

## Expected failures

| Symptom | Likely cause |
|---------|----------------|
| OAuth missing org scopes | App lacks Community Management product |
| `list_my_organizations` empty | User is not Page admin |
| `PERMISSION_DENIED` on create | Token lacks `w_organization_social` or org not in ACL list |
| `organization_urn must be a Company Page you administer` | URN not from `list_my_organizations` |

## Personal posting

Use [`../../linkedin-mcp/docs/operations/manual-testing.md`](../../linkedin-mcp/docs/operations/manual-testing.md) — not this server.
