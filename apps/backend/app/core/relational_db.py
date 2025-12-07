from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession, 
    AsyncEngine, 
    async_sessionmaker,
    create_async_engine
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from typing import Generator, AsyncGenerator
from functools import lru_cache

from ..models import Base
from .config import settings


@lru_cache(maxsize=1)
def _make_sync_engine() -> Engine:
    """
    Create Sync DB Engine
    """
    engine = create_engine(settings.SYNC_REL_DB_URL)
    return engine


@lru_cache(maxsize=1)
def _make_async_engine() -> AsyncEngine:
    """
    Create Async DB Engine 
    """
    engine = create_async_engine(settings.ASYNC_REL_DB_URL)
    return engine



sync_engine: Engine = _make_sync_engine()
async_engine: AsyncEngine = _make_async_engine()


# sync session factory
SessionLocal: sessionmaker[Session] = sessionmaker(
    autoflush=False, autocommit=False, bind=sync_engine
)

# async session factory 
AsyncSessionsLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
   bind=async_engine, autoflush=False, expire_on_commit=False
)


def get_sync_db_session() -> Generator[Session, None, None]:
    """
    Create transactional DB session that will commit
    in the case that no exceptions occurred, or else
    it will rollback

    Note: This function creates a Generator
    that works will with FastAPI's "Depends" functionality
    """
    db = SessionLocal()

    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    

async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Create transactional async DB session
    """
    
    async with AsyncSessionsLocal() as session:
        try:
            yield session 
            await session.commit() 
        except Exception:
            await session.rollback() 
            raise 



def init_db() -> None:
    """
    Initalize necessary DB tables used through application
    """
    Base.metadata.create_all(bind=sync_engine)
