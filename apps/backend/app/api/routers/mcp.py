from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from app.services.mcp import MCPService
from app.pydantic import MCPConfig as PydanticMCPConfig
from ..svc_deps import get_mcp_svc

from uuid import UUID
import logging

router = APIRouter(prefix="/mcp/configs")

logger = logging.getLogger(__name__)

@router.get("/", summary="Retrieve all MCP configurations")
def get_mcp_configs(
    svc: MCPService = Depends(get_mcp_svc)
):
    """
    Retrieve all MCP configurations
    """
    try:
        logging.info("Recieved request to get all MCP configurations")
        configs = svc.get_mcp_configs()
        return [
            {
                "id": c.id,
                "name": c.name,
                "transport_type": c.transport_type.value,
                "timeout": c.timeout,
                "config": c.config,
                "data_sources": [
                    {
                        "id": link.data_source.id,
                        "name": link.data_source.name,
                        "provider": link.data_source.provider,
                        "url": link.data_source.url
                    }
                    for link in c.data_source_mcp_configs
                ]
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
        logging.info(f"Recieved request to create MCP configuration: {request}")
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

@router.delete("/{mcp_config_id}", summary="Delete a specific MCP configuration")
def delete_mcp_config(
    mcp_config_id: UUID,
    svc: MCPService = Depends(get_mcp_svc)
):
    """
    Delete a specific MCP configuration
    """
    try:
        svc.delete_mcp(mcp_config_id)
        return {"id": mcp_config_id, "status": "deleted"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
