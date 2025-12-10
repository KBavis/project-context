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
import threading


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

# mappings for each thread to its corresponding engine 
_thread_local_sync_engines = {} 
_thread_local_async_engines = {}
_main_thread_id = threading.get_ident()


def get_sync_session_maker() -> sessionmaker[Session]:
    """
    Get sync session maker for current thread (ensuring thread safety)
        - Main Thread: use the main engine
        - Worker Thread: creates & caches thread-specific engine
    """

    current_thread_id = threading.get_ident() 

    # Main Thread - use the main engine
    if current_thread_id == _main_thread_id:
        return sessionmaker(
            autoflush=False,
            autocommit=False,
            bind=sync_engine
        )


    # Worker Thread - create or re-use thread specific engine 
    if current_thread_id not in _thread_local_sync_engines:
        thread_engine = create_engine(settings.SYNC_REL_DB_URL)
        _thread_local_sync_engines[current_thread_id] = thread_engine

    return sessionmaker(
        autoflush=False, 
        autocommit=False,
        bind=_thread_local_sync_engines[current_thread_id]
    )


def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    """
    Get an async session maker for current thread (ensuring thread safety)
    - Main Thread: use cached main engine
    - Worker Thread: create & cache thread-specific engine
    """

    current_thread_id = threading.get_ident()
    
    # Main Thread - use the main engine
    if current_thread_id == _main_thread_id:
        return async_sessionmaker(
            bind=async_engine,
            autoflush=False,
            expire_on_commit=False
        )
    
    # Worker Thread - create or re-use thread specific engine
    if current_thread_id not in _thread_local_async_engines:
        thread_engine = create_async_engine(
            settings.ASYNC_REL_DB_URL,
            pool_pre_ping=True,
        )
        _thread_local_async_engines[current_thread_id] = thread_engine
    
    return async_sessionmaker(
        bind=_thread_local_async_engines[current_thread_id],
        autoflush=False,
        expire_on_commit=False
    )




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
    

async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Create transactional async DB session
    """
    session_maker = get_async_session_maker()
    
    async with session_maker() as session:
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
