---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# API Key Query Endpoints Incomplete

## Description
Three related issues exist with API key query functionality:

### Issue 1: ListApiKeys Missing Sessions and Environs
`GET /api/v1/apikey` does not include bound sessions or environment variables per API key in the response, as required by `features/19api_key_required.md`:
> 查询 api_key 信息时，也需要一并显示api_key对应的sessions、environs等信息。

### Issue 2: User Cannot Query Own API Key
`GET /api/v1/apikey` is admin-only. User-role API keys have no endpoint to view their own key information (name, role, rate_limit, bound sessions, etc.). Per `features/19api_key_required.md`:
> user: Can only query api_key info

### Issue 3: Missing Single Key Retrieval Endpoint
There is no `GET /api/v1/apikey/{api_key_id}` endpoint for retrieving a single API key's details.

## Root Cause
The API key routes were implemented with admin-only list/delete/create endpoints, but user self-query and detailed response enrichment were not implemented.

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/api/routes/api_key.py`
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/storage/api_key_manager/base.py`
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/storage/api_key_manager/sql.py`

## Proposed Fix
1. **Enrich ListApiKeys response**: For each API key, include:
   - `sessions`: list of bound session IDs
   - `environs`: dict of key-value environment variables

2. **Allow user self-query**: Modify `GET /api/v1/apikey` to:
   - If caller is admin: return all API keys (current behavior)
   - If caller is user: return only their own API key info

3. **Add single key endpoint**: Implement `GET /api/v1/apikey/{api_key_id}`:
   - Admin: can query any key
   - User: can only query their own key (return 403 otherwise)
   - Response includes sessions and environs

## Impact
- Users cannot view their own API key details
- Admin cannot see full API key configuration (sessions + environs) in list view
- No way to retrieve a single API key's complete information
