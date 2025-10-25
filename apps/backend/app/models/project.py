from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import String

if TYPE_CHECKING:
    from .project_data import ProjectData

class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_name: Mapped[str] = mapped_column(nullable=False)
    epics: Mapped[List[str]] = mapped_column(ARRAY(String))

    #TODO: Create association table for Team and Project

    # many to many relationship with DataSource
    project_data: Mapped[List["ProjectData"]] = relationship(back_populates="project")
