from __future__ import annotations
from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List, Dict
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import String
from uuid import UUID
from sqlalchemy import text, ForeignKey, Table, Column

if TYPE_CHECKING:
    from .project_data import ProjectData
    from .conversation import Conversation


project_dependencies = Table(
    "project_dependencies",
    Base.metadata,
    Column("dependency_id", ForeignKey("project.id"), primary_key=True),
    Column("dependent_id", ForeignKey("project.id"), primary_key=True),
)


class Project(Base):
    __tablename__: str = "project"

    id: Mapped["UUID"] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_name: Mapped[str] = mapped_column(nullable=False)
    parent_issues: Mapped[List[str]] = mapped_column(ARRAY(String))

    dependent_projects: Mapped[List["Project"]] = relationship(
        "Project",
        secondary=project_dependencies, # tell SQLAchemy that relationship is in project_dependencies table
        primaryjoin="Project.id == project_dependencies.c.dependency_id", # find the 'source' project (i.e self)
        secondaryjoin="Project.id == project_dependencies.c.dependent_id", # find the 'destination' project (i.e dependent project)
        backref="dependencies",
    )

    lob: Mapped[str] = mapped_column(nullable=False, comment="Line of Business")
    meta_data: Mapped[List[str]] = mapped_column(ARRAY(String))
    description: Mapped[str] = mapped_column(nullable=True)

    # TODO: Create association table for Team and Project

    # many to many relationship with DataSource
    project_data: Mapped[List["ProjectData"]] = relationship(
        "ProjectData",
        back_populates="project"
    )


    # one to many relationship with Conversation 
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="project", 
        cascade="all, delete-orphan"
    )

