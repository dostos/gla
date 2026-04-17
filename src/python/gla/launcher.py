#!/usr/bin/env python3
"""GLA Launcher — runs engine + REST API in one process.

Usage:
    python -m gla.launcher [options]

The launcher prints environment variables needed to connect a shim:
    GLA_SOCKET_PATH=/tmp/gla.sock
    GLA_SHM_NAME=/gla_capture
    GLA_AUTH_TOKEN=<random token>
"""
import argparse
import secrets
import signal
import sys
import threading

def main():
    parser = argparse.ArgumentParser(description="GLA Engine + REST API")
    parser.add_argument("--backend", default="native",
                        choices=["native", "renderdoc"],
                        help="Capture backend to use (default: native)")
    parser.add_argument("--capture-file", default=None,
                        help="Path to a .rdc capture file (renderdoc backend only)")
    parser.add_argument("--socket", default="/tmp/gla.sock",
                        help="Unix socket path for shim connections")
    parser.add_argument("--shm", default="/gla_capture",
                        help="POSIX shared memory name")
    parser.add_argument("--shm-slots", type=int, default=4,
                        help="Number of ring buffer slots")
    parser.add_argument("--slot-size", type=int, default=64 * 1024 * 1024,
                        help="Size of each ring buffer slot in bytes")
    parser.add_argument("--port", type=int, default=18080,
                        help="REST API port")
    parser.add_argument("--token", default=None,
                        help="Auth token (auto-generated if not set)")
    args = parser.parse_args()

    token = args.token or secrets.token_urlsafe(32)

    if args.backend == "native":
        # Import C++ bindings
        import _gla_core

        # Create engine
        engine = _gla_core.Engine(args.socket, args.shm, args.shm_slots, args.slot_size)

        # Start engine in background thread
        engine_thread = threading.Thread(target=engine.run, daemon=True, name="gla-engine")
        engine_thread.start()

        # Create query engine
        normalizer = _gla_core.Normalizer()
        qe = _gla_core.QueryEngine(engine.frame_store(), normalizer)

        from gla.backends.native import NativeBackend
        provider = NativeBackend(qe, engine=engine)

    elif args.backend == "renderdoc":
        if not args.capture_file:
            parser.error("--capture-file is required for the renderdoc backend")

        from gla.backends.renderdoc import RenderDocBackend
        provider = RenderDocBackend(args.capture_file)
        engine = None
        engine_thread = None

    else:
        raise ValueError(f"Unknown backend: {args.backend}")

    # Create FastAPI app
    from gla.api.app import create_app
    app = create_app(provider=provider, auth_token=token)

    # Print connection info
    if args.backend == "native":
        print(f"GLA_SOCKET_PATH={args.socket}")
        print(f"GLA_SHM_NAME={args.shm}")
    print(f"GLA_AUTH_TOKEN={token}")
    print(f"GLA listening on http://127.0.0.1:{args.port}")
    sys.stdout.flush()

    # Handle SIGTERM gracefully
    def shutdown(sig, frame):
        if engine is not None:
            engine.stop()
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Run FastAPI (blocking)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")

    if engine is not None:
        engine.stop()
    if engine_thread is not None:
        engine_thread.join(timeout=5)

if __name__ == "__main__":
    main()
