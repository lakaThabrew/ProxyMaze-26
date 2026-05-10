import asyncio
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from . import state, routes, monitoring, webhooks

@asynccontextmanager
async def app_lifecycle_manager(app: FastAPI):
    state.event_loop_ref = asyncio.get_running_loop()
    state.probe_trigger = asyncio.Event()
    state.dispatch_buffer = asyncio.Queue()
    state.dispatcher_process = asyncio.create_task(webhooks.event_dispatcher_loop())
    monitor_task = asyncio.create_task(monitoring.background_monitoring_cycle())
    try:
        yield
    finally:
        monitor_task.cancel()
        if state.dispatcher_process: state.dispatcher_process.cancel()
        await asyncio.gather(monitor_task, state.dispatcher_process, return_exceptions=True)
        state.dispatcher_process = None
        state.dispatch_buffer = None
        state.event_loop_ref = None
        state.probe_trigger = None

app = FastAPI(title="ProxyMaze", lifespan=app_lifecycle_manager)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema: return app.openapi_schema
    openapi_schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    openapi_schema["servers"] = [{"url": "/", "description": "This deployment"}]
    app.openapi_schema = openapi_schema
    return openapi_schema

app.openapi = custom_openapi  # type: ignore
app.include_router(routes.router)
