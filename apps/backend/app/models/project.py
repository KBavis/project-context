from .base import Base
from sqlalchemy.orm import Mapped, mapped_column

class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_name: Mapped[str] = mapped_column(nullable=False)
