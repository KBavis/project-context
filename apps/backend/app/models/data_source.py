from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List

class DataSource(Base):
    __tablename__ = "data_source"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(nullable=False)
    source_name: Mapped[str] = mapped_column(nullable=False)
    
    data_source: Mapped[List["IngestionJob"]] = relationship(
        back_populates="data_source",
        cascade="all, delete-orphan"
    )
    