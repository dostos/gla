"""GLA FastAPI application factory.

MUST be served on 127.0.0.1 only (NFR-5.1 — localhost-only binding).
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


def create_app(provider=None, auth_token: str = "",
               # Legacy kwargs for backward compatibility
               query_engine=None, engine=None,
               scene_reconstructor=None) -> FastAPI:
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
        scene_reconstructor: **Deprecated** — passed through to ``NativeBackend``
            when *query_engine* is used.

    Returns:
        Configured FastAPI application.  Bind to 127.0.0.1 when serving.
    """
    # ------------------------------------------------------------------
    # Backward compatibility: wrap raw query_engine in NativeBackend
    # ------------------------------------------------------------------
    if provider is None:
        if query_engine is None:
            raise ValueError("Either 'provider' or 'query_engine' must be given")

        if scene_reconstructor is None:
            try:
                from _gla_core import SceneReconstructor  # type: ignore
                scene_reconstructor = SceneReconstructor()
            except ImportError:
                scene_reconstructor = None

        from gla.backends.native import NativeBackend
        provider = NativeBackend(query_engine, scene_reconstructor, engine)

    app = FastAPI(title="GLA", version="0.1.0")

    app.state.provider = provider
    app.state.auth_token = auth_token

    # Legacy attributes — kept so old code that accesses these directly
    # (e.g. tests that haven't been updated) continues to work.
    app.state.query_engine = getattr(provider, "_qe", None)
    app.state.engine = getattr(provider, "_engine", None)
    app.state.scene_reconstructor = getattr(provider, "_scene", None)

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

    app.include_router(frames_router, prefix="/api/v1")
    app.include_router(drawcalls_router, prefix="/api/v1")
    app.include_router(pixel_router, prefix="/api/v1")
    app.include_router(control_router, prefix="/api/v1")
    app.include_router(scene_router, prefix="/api/v1")
    app.include_router(diff_router, prefix="/api/v1")

    return app
