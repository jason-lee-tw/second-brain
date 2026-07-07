from collections.abc import Generator

from sqlmodel import Session, create_engine

from second_brain.config import settings

engine = create_engine(settings.database_url, echo=False)


def get_session() -> Generator[Session, None, None]:
  """FastAPI dependency that yields a SQLModel session and closes it on exit."""
  with Session(engine) as session:
    yield session
