"""Database connection helpers."""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def get_engine():
    """Create a SQLAlchemy engine from DATABASE_URL."""
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required. Set it in your environment or .env file."
        )

    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")

    return create_engine(url, connect_args={"connect_timeout": 10})
