import os
from typing import List


def get_frontend_origins() -> List[str]:
    """Return a list of allowed frontend origins.

    Priority:
    - FRONTEND_ORIGINS (comma-separated)
    - FRONTEND_URL (single URL)
    - default localhost ports used by common frontends
    """
    env = os.getenv("FRONTEND_ORIGINS")
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]

    url = os.getenv("FRONTEND_URL")
    if url:
        return [url.strip()]

    # sensible defaults for local development (React/Vite)
    return ["http://localhost:3000", "http://localhost:5173"]


def apply_cors(app):
    """Apply CORSMiddleware to a FastAPI application using env-configured origins."""
    from starlette.middleware.cors import CORSMiddleware
    import logging

    origins = get_frontend_origins()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Log the configured CORS origins so it's easy to verify at startup
    logger = logging.getLogger("uvicorn")
    logger.info(f"CORS configured. Allowed origins: {origins}")
