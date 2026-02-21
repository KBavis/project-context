from .base import Base
from sqlalchemy import text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List
from uuid import UUID

if TYPE_CHECKING:
    from .project import Project
    from .file_collection import FileCollection
    from .file import File

class Citation(Base):
    # TODO: we should create a linking table between a citation and a message 
    # This way, we can get the citations in the the LLM response by retrieving the message 

    __tablename__: str = "citation"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        index=True,
        server_default=text("gen_random_uuid()")
    )

    url: Mapped[str] = mapped_column(
        nullable=False,
        index=True,
        comment="Direct access URL to the file"
    )

    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("file.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to File that this citation belongs to"
    )

    # one to one relationship with File
    file: Mapped["File"] = relationship(
        "File",
        back_populates="citation"
    )
