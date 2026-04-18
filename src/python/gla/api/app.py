"""GLA FastAPI application factory.

MUST be served on 127.0.0.1 only (NFR-5.1 — localhost-only binding).
"""
import base64
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


def safe_json_response(data, status_code=200):
    """JSONResponse with bytes → base64 encoding.

    Use this instead of returning plain dicts from route handlers so that
    FastAPI skips pydantic serialization (which crashes on raw bytes from
    pybind11 shader parameter data).
    """
    def default(obj):
        if isinstance(obj, (bytes, bytearray)):
            return base64.b64encode(obj).decode("ascii")
        raise TypeError(f"Not serializable: {type(obj)}")
    body = json.dumps(data, default=default)
    return JSONResponse(content=json.loads(body), status_code=status_code)


def create_app(provider=None, auth_token: str = "",
               metadata_store=None,
               framework_query_engine=None,
               # Legacy kwargs for backward compatibility
               query_engine=None, engine=None) -> FastAPI:
    """Create and configure the GLA REST API application.

    Args:
        provider: A :class:`~gla.backends.base.FrameProvider` instance.
            When *None*, a ``query_engine`` must be supplied and it will
            be wrapped in a :class:`~gla.backends.native.NativeBackend`.
        auth_token: Bearer token required on every request.  Empty string
            disables auth.
        query_engine: **Deprecated** — pass a *provider* instead.  Kept for
            backward compatibility: if supplied without *provider*, it is
            wrapped in a :class:`NativeBackend`.
        engine: **Deprecated** — passed through to ``NativeBackend`` when
            *query_engine* is used.

    Returns:
        Configured FastAPI application.  Bind to 127.0.0.1 when serving.
    """
    # ------------------------------------------------------------------
    # Backward compatibility: wrap raw query_engine in NativeBackend
    # ------------------------------------------------------------------
    if provider is None:
        if query_engine is None:
            raise ValueError("Either 'provider' or 'query_engine' must be given")

        from gla.backends.native import NativeBackend
        provider = NativeBackend(query_engine, engine)

    app = FastAPI(title="GLA", version="0.1.0")

    app.state.provider = provider
    app.state.auth_token = auth_token

    # Metadata store for framework plugin sidecar data
    if metadata_store is None:
        from gla.framework.metadata_store import MetadataStore
        metadata_store = MetadataStore()
    app.state.metadata_store = metadata_store

    # Framework query engine — auto-create from provider + metadata_store if not provided
    if framework_query_engine is None and metadata_store:
        from gla.framework.query_engine import FrameworkQueryEngine
        framework_query_engine = FrameworkQueryEngine(provider, metadata_store)
    app.state.framework_query_engine = framework_query_engine

    # Legacy attributes — kept so old code that accesses these directly
    # (e.g. tests that haven't been updated) continues to work.
    app.state.query_engine = getattr(provider, "_qe", None)
    app.state.engine = getattr(provider, "_engine", None)

    @app.middleware("http")
    async def check_auth(request: Request, call_next):
        raw_header = request.headers.get("Authorization", "")
        token = raw_header.removeprefix("Bearer ").strip()
        if token != request.app.state.auth_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token"},
            )
        return await call_next(request)

    from .routes_frames import router as frames_router
    from .routes_drawcalls import router as drawcalls_router
    from .routes_pixel import router as pixel_router
    from .routes_control import router as control_router
    from .routes_scene import router as scene_router
    from .routes_diff import router as diff_router
    from .routes_metadata import router as metadata_router
    from .routes_objects import router as objects_router
    from .routes_passes import router as passes_router
    from .routes_explain import router as explain_router

    app.include_router(frames_router, prefix="/api/v1")
    app.include_router(drawcalls_router, prefix="/api/v1")
    app.include_router(pixel_router, prefix="/api/v1")
    app.include_router(control_router, prefix="/api/v1")
    app.include_router(scene_router, prefix="/api/v1")
    app.include_router(diff_router, prefix="/api/v1")
    app.include_router(metadata_router, prefix="/api/v1")
    app.include_router(objects_router, prefix="/api/v1")
    app.include_router(passes_router, prefix="/api/v1")
    app.include_router(explain_router, prefix="/api/v1")

    return app
