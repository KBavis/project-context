from __future__ import annotations
from .base import Base 
from uuid import UUID
from typing import TYPE_CHECKING, List

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import text, ForeignKey


if TYPE_CHECKING:
    from .project import Project
    from .message import Message
    from .execution_token_usage import ExecutionTokenUsage


class Conversation(Base):
    __tablename__: str = "conversation"


    id: Mapped["UUID"] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    summary: Mapped[str] = mapped_column(
        nullable=True, 
        comment="One line summary of what the inital ask of this new conversation was"
    )

    # TODO: Add user relationship (as a Conversation will only pertain to single user)

    total_tokens: Mapped[int] = mapped_column(
        nullable=False,
        default=text("0"),
        comment="The total number of tokens (both input & output) this Conversation contains"
    )

    max_tokens: Mapped[int] = mapped_column(
        nullable=False,
        comment="The maximum number of tokens that can be sent in this Conversation"
    )

    ll_model_name: Mapped[str] = mapped_column(
        nullable=False,
        comment="The name of the LL Model this Conversation was setup to use"
    )

    ll_model_provider: Mapped[str] = mapped_column(
        nullable=False,
        comment="The LL Model provider configured for this Conversation"
    )

    total_execution_tokens: Mapped[int] = mapped_column(
        nullable=False,
        default=text("0"),
        comment="The total execution tokens used across all agentic turns during course of conversation"
    )

    # many to one relationship with Project 
    project_id: Mapped["UUID"] = mapped_column(
        ForeignKey("project.id")
    )
    project: Mapped["Project"] = relationship(back_populates="conversations")


    # one to many relationship with Message
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan"
    )

    # one to many relationship with ExecutionTokenUsage
    execution_token_usages: Mapped[List["ExecutionTokenUsage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan"
    )