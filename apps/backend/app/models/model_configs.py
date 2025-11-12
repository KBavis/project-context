from uuid import UUID
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import text, ForeignKey

from .base import Base

if TYPE_CHECKING:
    from .project import Project


class ModelConfigs(Base): 
    """
    Entity to store selected model configurations used for a given project
    """

    __tablename__ = "model_configs"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"))

    docs_embedding_provider: Mapped[str] = mapped_column(nullable=True)
    docs_embedding_model: Mapped[str] = mapped_column(nullable=True)

    code_embedding_provider: Mapped[str] = mapped_column(nullable=True)
    code_embedding_model: Mapped[str] = mapped_column(nullable=True)
    
    project: Mapped["Project"] = relationship(
        back_populates="model_configs",
        uselist=False # ensure 1-1 relationship 
    )

