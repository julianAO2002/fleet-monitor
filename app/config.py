"""Application configuration.

This is the ONLY module in the project that reads the environment. Every other
module receives what it needs through ``get_settings()`` instead of reaching
for ``os.environ`` on its own (Single Responsibility). If configuration ever
moves to a secrets manager, this file changes and nothing else does.

Values come from environment variables, falling back to a local ``.env`` file
during development. Nothing is hardcoded, so the same image runs unchanged in
development, staging and production.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated configuration for the application.

    Pydantic reads each field from the environment variable of the same name
    (case-insensitive) and coerces it to the declared type. A malformed value
    such as ``STALE_AFTER_SECONDS=abc`` fails at startup with a clear message,
    instead of surfacing as a confusing error later at runtime.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ─────────────────────────────────
    app_name: str = "fleet-monitor"
    app_version: str = "0.1.0"
    environment: str = "development"

    # ── Database ────────────────────────────────────
    # Consumed from day 2 onwards, when the engine is created.
    database_url: str = "postgresql+psycopg://fleet:changeme@db:5432/fleet"

    # ── Node status thresholds (seconds) ────────────
    # Kept as configuration because operating conditions differ per route:
    # a satellite link in the North Atlantic tolerates longer silences than a
    # node in port. Changing them must not require rebuilding the image.
    stale_after_seconds: int = 120
    offline_after_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    """Return the application settings.

    Exposed as a function rather than a module-level instance so it can be
    injected with FastAPI's ``Depends`` and overridden in tests. ``lru_cache``
    makes it a singleton in practice: the environment is parsed once, and every
    caller after that gets the same object.
    """
    return Settings()
