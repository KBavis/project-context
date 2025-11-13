from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime


class Base(DeclarativeBase):
    """
    Base model for our Tables, each with a created at and updated at field
    """

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, index=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
