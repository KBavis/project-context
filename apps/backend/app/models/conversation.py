from .base import Base 
from uuid import UUID
from typing import TYPE_CHECKING, List

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import text, ForeignKey


if TYPE_CHECKING:
    from .project import Project
    from .message import Message


class Conversation(Base):
    __tablename__ = "conversation"


    id: Mapped[UUID] = mapped_column(
        primary_key=True, index=True, server_default=text("get_random_uuid()")
    )
    summary: Mapped[str] = mapped_column(
        nullable=True, 
        comment="One line summary of what the inital ask of this new conversation was"
    )

    # TODO: Add user relationship (as a Conversation will only pertain to single user)



    # many to one relationship with Project 
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project.id")
    )
    project: Mapped["Project"] = relationship(back_populates="conversations")


    # one to many relationship with Message
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan"
    )