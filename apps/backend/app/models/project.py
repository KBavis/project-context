from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import String
from uuid import UUID
from sqlalchemy import text, ForeignKey

if TYPE_CHECKING:
    from .project_data import ProjectData
    from .model_configs import ModelConfigs
    from .conversation import Conversation
    from .file_collection import FileCollection


class Project(Base):
    __tablename__ = "project"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_name: Mapped[str] = mapped_column(nullable=False)
    epics: Mapped[List[str]] = mapped_column(ARRAY(String))

    # TODO: Create association table for Team and Project

    # one to one relationship with ModelConfigs
    model_configs: Mapped["ModelConfigs"] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    # many to many relationship with DataSource
    project_data: Mapped[List["ProjectData"]] = relationship(back_populates="project")


    # one to many relationship with Conversation 
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    # one to many relationship with FileCollection
    file_collections: Mapped[List["FileCollection"]] = relationship(
        back_populates="project", 
        cascade="all, delete-orphan"
    )

