from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

class IngestionJob(Base):
    __tablename__ = "ingestion_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    processing_status: Mapped[str] = mapped_column(nullable=False)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"))

    data_source: Mapped["DataSource"] = relationship(
        back_populates="ingestion_jobs"
    )


    