from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status

from app.services import ProjectService
from app.pydantic import ProjectRequest
from ..svc_deps import get_project_svc

from typing import List
from uuid import UUID

router = APIRouter(prefix="/projects")

@router.post("/", summary="Create new project")
def create_project(
    project: ProjectRequest, 
    svc: ProjectService = Depends(get_project_svc)
):
    """
    Create a new Project for RAG Pipeline to account for
    """

    try:
        return svc.create_project(project)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.get("/", summary="Retrieve all projects")
def get_projects(
    svc: ProjectService = Depends(get_project_svc)
) -> List[dict]:
    """
    Fetch all persisted Projects

    TODO: Only fetch Projects authenticated user is able to see
    """

    try:
        return svc.get_all_projects()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post("/{project_id}/data-sources/{data_source_id}", summary="Link data source to project")
def link_data_source(
    project_id: UUID,
    data_source_id: UUID,
    svc: ProjectService = Depends(get_project_svc)
):
    """
    Associate an existing Data Source with a Project
    """

    try:
        return svc.link_data_source_to_project(project_id, data_source_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
