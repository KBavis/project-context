from __future__ import annotations
from contextlib import asynccontextmanager
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession, 
    AsyncEngine, 
    async_sessionmaker,
    create_async_engine
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from typing import Generator, AsyncGenerator
from functools import lru_cache

from ..models import Base
from .config import settings
import threading
from convextvars import ContextVar


#################################################################
# Sync & Async Engine Defintions
# ###############################################################

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
    Create Async DB Engine (NOT cached - allows for per-thread creation)
    """
    engine = create_async_engine(settings.ASYNC_REL_DB_URL, pool_pre_ping=True, pool_size=10)
    return engine


sync_engine: Engine = _make_sync_engine()
async_engine: AsyncEngine = _make_async_engine() 


#############################################################################################
# Logic to create SessionFactories for both Async/Sync Engine
# NOTE: This logic takes into consideration the ability to create new session on Worker thread
#############################################################################################

# store main thread ID 
_main_thread_id = threading.get_ident()


def get_sync_session_maker() -> sessionmaker[Session]:
    """
    Get sync session maker for current thread (ensuring thread safety)
        - Main Thread: use the main engine
        - Worker Thread: creates & caches thread-specific engine
    """

    _current_thread_id = threading.get_ident() 

    # Main Thread - use the main engine
    if _current_thread_id == _main_thread_id:
        return sessionmaker(
            autoflush=False,
            autocommit=False,
            bind=sync_engine
        )


    # Worker Thread - create or re-use thread specific engine 
    _thread_engine = create_engine(
        settings.SYNC_REL_DB_URL, 
        pool_pre_ping=True, 
        poolclass=NullPool # don't pool connection in Worker thread
    )

    return sessionmaker(
        autoflush=False, 
        autocommit=False,
        bind=_thread_engine
    )


def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    """
    Get an async session maker for current thread (ensuring thread safety)
    - Main Thread: use cached main engine
    - Worker Thread: create & cache thread-specific engine
    """

    _current_thread_id = threading.get_ident()
    
    # Main Thread - use the main engine
    if _current_thread_id == _main_thread_id:
        return async_sessionmaker(
            bind=async_engine,
            autoflush=False,
            expire_on_commit=False
        )
    
    # Worker Thread - create or re-use thread specific engine
    _thread_engine = create_async_engine(
        settings.ASYNC_REL_DB_URL,
        pool_pre_ping=True,
        poolclass=NullPool # don't pool connections on worker thread
    )
    
    return async_sessionmaker(
        bind=_thread_engine,
        autoflush=False,
        expire_on_commit=False
    )


async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Create a transactional async DB session for use as a FastAPI dependency
    (via Depends()). FastAPI's DI system drives this generator directly:
    it resumes past the `yield` to commit/rollback once the request
    handler returns. Not usable with `async with` — see
    get_async_db_session_context for that.
    """
    session_maker = get_async_session_maker()
    
    async with session_maker() as session:
        try:
            yield session 
            await session.commit() 
        except Exception:
            await session.rollback() 
            raise 


def get_sync_db_session() -> Generator[Session, None, None]:
    """
    Create transactional DB session that will commit
    in the case that no exceptions occurred, or else
    it will rollback

    Note: This function creates a Generator
    that works will with FastAPI's "Depends" functionality
    """
    session_maker = get_sync_session_maker() 
    db = session_maker()

    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()



#####################################
# Background Task DB Session Logic
#####################################


@asynccontextmanager
async def get_async_db_session_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Create a transactional async DB session for use outside FastAPI's
    request lifecycle (e.g. background tasks).

    Wrapped in @asynccontextmanager so it can be driven via `async with`,
    since plain async generators don't implement __aenter__/__aexit__ on
    their own. The session logic here is identical to get_async_db_session;
    use this version anywhere FastAPI's DI isn't managing the lifecycle.
    """
    session_maker = get_async_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# Ambient Session Management
_current_session: ContextVar[AsyncSession | None] = ContextVar("current_session", default=None)

def get_current_session() -> AsyncSession:
    """
    Return the ambient DB session bound for the current background unit of work

    Raise Exception in the case that this function is called outside an `ambient_session()` scope,
    as normal, non-background processing should use Dependency Injected sessions instead
    """
    s = _current_session.get() 
    if s is None:
        # NOTE: This will happen if _current_session.set() was never called (e.g. not in a ambient_session() block)
        raise RuntimeError("ambient_session unavailable - must run inside ambietn_session()")
    return s


@asynccontextmanager
async def ambient_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Open transactional Async Session & Bind as the Ambient Session for the duration of the Blokc 

    NOTE: This is used during background processing of `Jobs` and `Tasks`. When running `run_project_job()`,
    we will spawn many `asyncio.Tasks` concurrently (i.e `asyncio.gather(....)`) and we want to scope a particular 
    Async DB session per `asyncio.Task` without any risk of leaking state between Tasks
    """
    async with get_async_db_session_context() as session:
        token = _current_session.set(session) # bind ambient session to current Task
        try:
            yield session
        finally:
            _current_session.reset(token) # reset ambient session



######################################################
# Initlaize DB Tables for 1st Time Use of Application
# NOTE: This likely can be done async via async engine
######################################################


def init_db() -> None:
    """
    Initalize necessary DB tables used through application
    """

    # prevent `data_chunks_docstore` table from being created 
    # NOTE: This is because we wnat PostgresKVStore to create this for us in order to 
    # prevent corrupted the internal strucutre of the table 
    tables_to_create = [
        table for table in Base.metadata.tables.values()
        if table.name != 'data_chunks_docstore'
    ]
    Base.metadata.create_all(bind=sync_engine, tables=tables_to_create)
