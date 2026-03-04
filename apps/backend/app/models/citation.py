from .base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, UUID
from typing import List
from sqlalchemy.orm import relationship
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .message import Message
    from .file import File


class Citation(Base):
    __tablename__: str = "citation"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)

    file_id: Mapped[UUID] = mapped_column(UUID)
    message_id: Mapped[UUID] = mapped_column(UUID)

    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="citations"
    )


    file: Mapped["File"] = relationship(
        "File",
        back_populates="citations", 
        cascade="all, delete-orphan"
    )