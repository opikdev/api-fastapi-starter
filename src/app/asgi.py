"""The ASGI app for `uvicorn app.asgi:app`, such as `make dev` with auto-reload."""

from app.config import load_settings
from app.log import configure_logging
from app.main import create_app

settings = load_settings()
configure_logging(settings.log_level)
app = create_app(settings)
