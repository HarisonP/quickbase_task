"""Command-line entry point that starts the API server."""

import argparse

import uvicorn

from backend.core.config import HOST, PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the API server.")
    parser.add_argument("--host", default=HOST, help="Interface to bind to.")
    parser.add_argument("--port", type=int, default=PORT, help="Port to listen on.")
    parser.add_argument(
        "--reload", action="store_true", help="Restart the server on code changes."
    )
    args = parser.parse_args()

    # Reload needs the app as an import string so uvicorn can re-import it.
    uvicorn.run(
        "backend.app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        env_file=".env",
        reload_dirs=["backend"] if args.reload else None,
    )


if __name__ == "__main__":
    main()
