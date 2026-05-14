from __future__ import annotations
from .base import Base
from typing import TYPE_CHECKING
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import ForeignKey
from uuid import UUID

if TYPE_CHECKING:
    from .data_source import DataSource
    from .mcp_config import MCPConfig

class DataSourceMCPConfig(Base):
    __tablename__: str = "data_source_mcp_config"

    data_source_id: Mapped["UUID"] = mapped_column(ForeignKey("data_source.id"), primary_key=True)
    mcp_config_id: Mapped["UUID"] = mapped_column(ForeignKey("mcp_config.id"), primary_key=True)

    # many to many relationship between DataSource and MCPConfig
    data_source: Mapped["DataSource"] = relationship(back_populates="data_source_mcp_configs")
    mcp_config: Mapped["MCPConfig"] = relationship(back_populates="data_source_mcp_configs")
