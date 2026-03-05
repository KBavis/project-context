from .base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, UUID, ForeignKey, text
from typing import List
from sqlalchemy.orm import relationship
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .message import Message
    from .file import File


class Citation(Base):
    __tablename__: str = "citation"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))

    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("file.id"),
        comment="The ID of the file that this citation is associated with"
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("message.id"),
        comment="The ID of the message that this citation is associated with"
    )

    # many to one relationship with Message
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="citations"
    )

    # many to one relationship with File
    file: Mapped["File"] = relationship(
        "File",
        back_populates="citations", 
    )