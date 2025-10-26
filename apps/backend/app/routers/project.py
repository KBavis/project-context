from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core import get_db_session
from app.services import ProjectService
from app.pydantic import ProjectRequest
from typing import List

router = APIRouter(prefix="/projects")

@router.post("/", summary="Create new project")
def create_project(project: ProjectRequest, db: Session = Depends(get_db_session)):
    """
    Create a new Project for RAG Pipeline to account for
    """

    try:
        svc = ProjectService(db)
        return svc.create_project(project)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )

@router.get("/", summary="Retrieve all projects")
def get_projects(db: Session = Depends(get_db_session)) -> List[dict]:
    """
    Fetch all persisted Projects

    TODO: Only fetch Projects authenticated user is able to see
    """

    try:
        svc = ProjectService(db)
        return svc.get_all_projects()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )