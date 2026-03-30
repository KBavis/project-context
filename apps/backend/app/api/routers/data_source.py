from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status

from app.services import DataSourceService
from app.pydantic import CreateDataSourceRequest
from ..svc_deps import get_data_source_svc

from uuid import UUID


router = APIRouter(prefix="/data/sources")


@router.get("/", summary="Retrieve all data sources")
def get_data_sources(
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Retrieve all data sources
    """
    try:
        return svc.get_all_data_sources()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post("/", summary="Connect to external data source")
def create_datasource(
    request: CreateDataSourceRequest, 
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Connect application to an external datasource in order to ingest data from
    """

    try:
        return svc.create_data_source(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post("/{data_source_id}/mcp/{mcp_config_id}", summary="Link a Data Source to an MCP Configuration")
def link_data_source_to_mcp_config(
    data_source_id: UUID,
    mcp_config_id: UUID,
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Link a Data Source to an MCP Configuration
    """
    try:
        return svc.link_mcp_config_to_data_source(data_source_id, mcp_config_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )

# TODO: Add logic to associate existing DataSource to new Project

@router.get("/{project_id}", summary="Get connected data sources")
def get_project_data_sources(
    project_id: UUID, 
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Retrieve data sources corresponding to a Project that the authenticated user is able to view
    """

    try:
        return svc.get_project_data_sources(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
