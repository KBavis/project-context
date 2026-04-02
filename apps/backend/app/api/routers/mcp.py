from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from app.services.mcp import MCPService
from app.pydantic import MCPConfig as PydanticMCPConfig
from ..svc_deps import get_mcp_svc
from uuid import UUID

router = APIRouter(prefix="/mcp/configs")

@router.get("/", summary="Retrieve all MCP configurations")
def get_mcp_configs(
    svc: MCPService = Depends(get_mcp_svc)
):
    """
    Retrieve all MCP configurations
    """
    try:
        configs = svc.get_mcp_configs()
        return [
            {
                "id": c.id,
                "name": c.name,
                "transport_type": c.transport_type.value,
                "timeout": c.timeout,
                "config": c.config,
                "data_source_id": c.data_source_id,
                "data_source": {
                    "id": c.data_source.id,
                    "name": c.data_source.name,
                    "provider": c.data_source.provider,
                    "url": c.data_source.url
                } if c.data_source else None
            } for c in configs
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )

@router.post("/", summary="Create a new MCP configuration")
def create_mcp_config(
    request: PydanticMCPConfig,
    svc: MCPService = Depends(get_mcp_svc)
):
    """
    Create a new MCP configuration
    """
    try:
        config = svc.create_mcp(request)
        return {
            "id": config.id,
            "name": config.name,
            "transport_type": config.transport_type.value,
            "timeout": config.timeout,
            "config": config.config
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )

@router.get("/{mcp_config_id}", summary="Retrieve a specific MCP configuration")
def get_mcp_config(
    mcp_config_id: UUID,
    svc: MCPService = Depends(get_mcp_svc)
):
    """
    Retrieve a specific MCP configuration
    """
    try:
        config = svc.get_mcp_by_id(mcp_config_id)
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP Configuration not found")
        return {
            "id": config.id,
            "name": config.name,
            "transport_type": config.transport_type.value,
            "timeout": config.timeout,
            "config": config.config
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
