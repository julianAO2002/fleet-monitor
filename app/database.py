"""Database engine and session management.

The engine is created once per process and owns a pool of connections. Sessions
are short-lived: one per request, opened on the way in and closed on the way
out, so a connection is never held while the process sits idle.

``get_session`` is the dependency every route handler uses to reach the
database. Handlers receive a session instead of importing one, which is what
makes it possible to point them at a throwaway database during tests without
changing their code.
"""

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    # Verify a pooled connection is still alive before handing it out. Vessels
    # run over links that drop; without this, the first query after an idle
    # period fails on a socket the pool still believes is open.
    pool_pre_ping=True,
    echo=False,
)


def init_db() -> None:
    """Create any table that does not exist yet.

    Adequate for this project, where the schema only ever grows. A system that
    needs to alter existing columns without losing data would use a migration
    tool such as Alembic; this is a deliberate simplification, not an oversight.
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a database session for the lifetime of one request.

    Declared as a generator so FastAPI runs the teardown after the response is
    produced: the ``with`` block closes the session even when the handler
    raises, returning the connection to the pool instead of leaking it.
    """
    with Session(engine) as session:
        yield session
