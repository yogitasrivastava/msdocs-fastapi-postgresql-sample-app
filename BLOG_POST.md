# Securing an MCP Server on Azure App Service with Microsoft Entra Authentication and Enabling Access via Agent Identity for Autonomous Agents

## Introduction

The **Model Context Protocol (MCP)** is rapidly becoming the standard for connecting AI agents to external tools and data sources. When you deploy an MCP server on **Azure App Service**, you need robust authentication to ensure only authorized clients can access it.

In this post, we will walk through how we secured a **FastMCP server** running on **Azure App Service** with **Microsoft Entra ID** authentication, and preauthorized **Microsoft Foundry** agent identities to call it — all without modifying a single line of application-level auth code. All resources are private and access is gated behind Entra ID.

[Aneep to add logging info]

## The Scenario

We have a FastAPI restaurant review application deployed on Azure App Service. We added an MCP server that exposes four tools:

| Tool | Description |
|------|-------------|
| `list_restaurants_mcp` | List all restaurants with average rating and review count |
| `get_details_mcp` | Get a restaurant's details and all its reviews |
| `create_review_mcp` | Add a new review to a restaurant |
| `create_restaurant_mcp` | Create a new restaurant |

The goal: allow a **MAF(Microsoft Agent Framework)** agent deployed to the **Microsoft Foundry** to securely call these tools using its agent identity, while rejecting all unauthorized requests.

## Architecture

```
Microsoft Foundry deployed Agent
    │
    │  client_credentials flow (MCP.Access app role)
    ▼
Azure App Service (EasyAuth v2, Return401)
    │
    │  JWT validated: issuer, audience, allowedClientApplications
    ▼
FastAPI + gunicorn (lifespan: on)
    │
    │  /mcp/mcp → FastMCP (stateless_http)
    ▼
MCP Tools → PostgreSQL
```

The key insight: **EasyAuth handles all authentication at the platform layer** — the application code never touches tokens or validates claims. This is clean separation of concerns.

## Step 1: Adding the MCP Server to FastAPI

First, we added `mcp[cli]` to our dependencies and created a simple MCP server:

```python
from mcp.server.fastmcp import FastMCP

# stateless_http=True is required for mounting under FastAPI
mcp = FastMCP("RestaurantReviewsMCP", stateless_http=True)

@mcp.tool()
async def list_restaurants_mcp() -> list[dict]:
    """List restaurants with their average rating and review count."""
    # ... database query logic
```

We mounted it in `app.py`:

```python
from .mcp_server import mcp, mcp_lifespan

app = FastAPI(lifespan=mcp_lifespan)
app.mount("/mcp", mcp.streamable_http_app())
```

### Critical: Gunicorn Lifespan Configuration

The MCP session manager requires lifespan events. Without this, **all MCP requests fail in production**:

```python
class MyUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {
        "loop": "asyncio",
        "http": "auto",
        "lifespan": "on",      # CRITICAL: must be "on" for MCP
    }
```

## Step 2: Deploying to Azure App Service

```bash
azd auth login
azd up
```

Before enabling auth, we verified the MCP endpoint worked:

```bash
curl -X POST https://<your-app>.azurewebsites.net/mcp/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## Step 3: Entra ID App Registration

We created an app registration with:

1. **Application ID URI**: `api://<client-id>`
2. **Delegated scope**: `user_impersonation` (for interactive users)
3. **App role**: `MCP.Access` with `allowedMemberTypes: ["Application"]` (for managed identities)
4. **Service Principal**: Required for app role assignments to work

```bash
# Create the app registration
az ad app create --display-name "my-mcp-server-auth" \
  --sign-in-audience AzureADMyOrg

# Add Application ID URI
az ad app update --id <client-id> \
  --identifier-uris "api://<client-id>"

# Create Service Principal (often missed!)
az ad sp create --id <client-id>
```

### The App Role

For managed identities (like Foundry agents) that use `client_credentials` flow, you need an **app role**, not a delegated scope:

```json
{
  "appRoles": [{
    "allowedMemberTypes": ["Application"],
    "displayName": "MCP.Access",
    "description": "Allow application to access MCP server",
    "isEnabled": true,
    "value": "MCP.Access"
  }]
}
```

## Step 4: Enabling App Service Authentication (EasyAuth)

We configured EasyAuth v2 via the ARM API with these key settings:

| Setting | Value | Why |
|---------|-------|-----|
| `runtimeVersion` | `~2` | v1 doesn't properly enforce auth |
| `unauthenticatedClientAction` | `Return401` | API behavior (no browser redirects) |
| `allowedAudiences` | `api://<client-id>`, `<client-id>` | Accept both audience formats |
| `allowedClientApplications` | Agent & Project identity IDs | Only these clients can call the API |

### Protected Resource Metadata (PRM)

PRM tells MCP clients how to authenticate. It's served automatically by EasyAuth:

```bash
az webapp config appsettings set \
  --name <app-name> --resource-group <rg> \
  --settings WEBSITE_AUTH_PRM_DEFAULT_WITH_SCOPES="api://<client-id>/user_impersonation"
```

The `/.well-known/oauth-protected-resource` endpoint returns:

```json
{
  "resource": "https://<app-name>.azurewebsites.net",
  "authorization_servers": [
    "https://login.microsoftonline.com/<tenant-id>/v2.0"
  ],
  "scopes_supported": [
    "api://<client-id>/user_impersonation"
  ]
}
```

## Step 5: Preauthorizing Foundry Agent Identities

Azure AI Foundry agents use managed identities of type `ServiceIdentity`. They authenticate via `client_credentials` flow and need:

1. An **app role assignment** granting them `MCP.Access`
2. Their appId listed in EasyAuth's **`allowedClientApplications`**

```bash
# Grant app role to the agent identity
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/<agent-principal-id>/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body '{
    "principalId": "<agent-principal-id>",
    "resourceId": "<your-app-sp-id>",
    "appRoleId": "<mcp-access-role-id>"
  }'
```

> **Important**: `ServiceIdentity` type principals **cannot** be added to `preAuthorizedApplications` — you'll get an `InvalidAppId` error. The app role assignment + `allowedClientApplications` approach is correct for managed identities.

## Testing: 22 Scenarios Across 3 Groups

We validated the setup with comprehensive test coverage across 3 groups.

### Group A: Without Authentication (8 tests)

With auth temporarily disabled to verify baseline MCP functionality, we confirmed the server works end-to-end:
- Root endpoint returns 200
- PRM endpoint returns 404 (it's served by EasyAuth, not the app)
- MCP `initialize`, `tools/list`, and all 4 tool calls succeed

### Group B: With Authentication (11 tests)

With auth enabled (the production configuration), we verified:
- **Negative cases**: No token → 401, fake token → 401, wrong audience → 401
- **PRM exemption**: The `.well-known/oauth-protected-resource` endpoint is accessible without auth (by design — clients need it to discover how to authenticate)
- **Positive cases**: Valid token → MCP `initialize`, `tools/list`, and all 4 tool calls succeed

### Group C: Python MCP Client (3 tests)

End-to-end programmatic tests using the `mcp` Python SDK:

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def test_with_auth():
    token = await get_token()  # client_credentials flow
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("list_restaurants_mcp", {})
```

## Key Lessons Learned

### 1. EasyAuth `runtimeVersion` must be `~2`

Version `~1` doesn't properly enforce authentication in all scenarios. We wasted time debugging before discovering this.

### 2. Service Principal creation is required

Without a service principal for your app registration, app role assignments will fail silently. Always run `az ad sp create --id <client-id>`.

### 3. `lifespan: "on"` is critical for MCP in production

The default gunicorn/uvicorn configuration may not run lifespan events. Without them, the MCP session manager never starts, and all requests fail with cryptic errors.

### 4. `ServiceIdentity` cannot use `preAuthorizedApplications`

Foundry agent identities are `ServiceIdentity` type — they require app role assignments, not the `preAuthorizedApplications` mechanism used for regular app-to-app consent.

### 5. PRM enables automatic auth discovery

With Protected Resource Metadata configured, MCP clients can automatically discover the authorization server and required scopes without manual configuration.

## Conclusion

By leveraging **EasyAuth v2** with **app roles** and **Protected Resource Metadata**, we secured an MCP server for Azure AI Foundry agents without writing any authentication code in the application. The platform handles JWT validation, audience checking, and client allowlisting — leaving the application code focused purely on business logic.

This pattern works for any MCP server on Azure App Service that needs to serve AI agents with managed identity authentication.

---

*Technologies used: FastAPI, FastMCP, Azure App Service, Microsoft Entra ID, Azure AI Foundry, EasyAuth v2, Protected Resource Metadata (PRM)*
