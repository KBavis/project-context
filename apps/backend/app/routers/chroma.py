from fastapi import APIRouter, HTTPException, status, Depends

from app.services import ChromaService
from app.core import get_db_session

from sqlalchemy.orm import Session

from uuid import UUID




router = APIRouter(prefix="/test/chroma")

# TODO: Make this endpoint admin only accessible

@router.get("/collection/total", summary="Get the total number of collections")
def get_collection_total (
    db: Session = Depends(get_db_session)
):
    """
    Get the total number of collections stored in ChromaDB
    """

    try:
        svc = ChromaService(db)
        return svc.get_total_number_of_collections()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  


@router.get("/{project_id}")
def get_documents(project_id: UUID, db: Session = Depends(get_db_session)):
    """
    Retrieve the documents associated with a particular project in Chroma 

    TODO: Allow for specification of a particular source_type (i.e DOCS or CODE)
    """

    try:
        svc = ChromaService(db)
        return svc.get_all_files(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  


@router.delete("/collection/{project_id}")
def delete_collection(project_id: UUID, db: Session = Depends(get_db_session)):
    """
    Retrieve the documents associated with a particular project in Chroma 

    TODO: Allow for specification of a particular source_type (i.e DOCS or CODE)
    """

    try:
        svc = ChromaService(db)
        return svc.delete_collection(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  


@router.delete("/collection/{project_id}/documents")
def delete_documents_from_collections(project_id: UUID, db: Session = Depends(get_db_session)):
    """
    Delete specific documents from existing collection

    TODO: Allow for specification of a particular source_type (i.e DOCS or CODE)
    """

    try:
        svc = ChromaService(db)
        return svc.delete_collection_documents(project_id, []) # TODO: Enforce passing of specific document ids to delete 
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  