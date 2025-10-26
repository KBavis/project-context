from sqlalchemy import create_engine
from .config import settings
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from typing import Generator
from ..models import (Base)



# create engine 
def _make_engine() -> Engine:
    """Create database Engine"""
    engine = create_engine(
        settings.REL_DB_URL,
        echo=True,
        echo_pool=True
    )
    return engine

engine: Engine = _make_engine()


# create session factory for FastAPI runtime 
SessionLocal: sessionmaker[Session] = sessionmaker(
    autoflush=False,
    autocommit=False,
    bind=engine
)

def get_db_session() -> Generator[Session, None, None]:
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


def init_db() -> None:
    """
    Initalize necessary DB tables used through application 
    """
    Base.metadata.create_all(bind=engine)

