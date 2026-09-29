import uvicorn
from fastapi import FastAPI

from mcp_server import mcp

MOUNT_PREFIX = "/api"
MCP_PATH = "/mcp"

mcp_app = mcp.http_app(path=MCP_PATH, transport="streamable-http")

app = FastAPI(lifespan=mcp_app.lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "restaurant-mcp-server"}


app.mount(MOUNT_PREFIX, mcp_app)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")