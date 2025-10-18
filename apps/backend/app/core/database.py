from sqlalchemy import create_engine
from .config import settings
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker



# create engine 
def _make_engine():
    """Create database Engine"""
    engine = create_engine(
        settings.DB_URL,
        echo=True,
        echo_pool=True
    )
    return engine

engine: Engine = _make_engine()




