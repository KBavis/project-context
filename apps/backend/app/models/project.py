from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .project_data import ProjectData

class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_name: Mapped[str] = mapped_column(nullable=False)

    # many to many relationship with DataSource
    project_data: Mapped[List["ProjectData"]] = relationship(back_populates="project")
