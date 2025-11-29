from fastapi import APIRouter, HTTPException, status, Depends

from app.services import ChromaService
from app.pydantic import DeleteCollectionDocsRequest

from ..svc_deps import get_chroma_svc



from uuid import UUID




router = APIRouter(prefix="/test/chroma")

# TODO: Make this endpoint admin only accessible

@router.get("/collection/total", summary="Get the total number of collections")
def get_collection_total (
    svc: ChromaService = Depends(get_chroma_svc)
):
    """
    Get the total number of collections stored in ChromaDB
    """

    try:
        return svc.get_total_number_of_collections()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  


@router.get("/{project_id}")
def get_documents(
    project_id: UUID, 
    svc: ChromaService = Depends(get_chroma_svc)
):
    """
    Retrieve the documents associated with a particular project in Chroma 

    TODO: Allow for specification of a particular source_type (i.e DOCS or CODE)
    """

    try:
        return svc.get_all_files(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  


@router.delete("/collection/{project_id}")
def delete_collection(
    project_id: UUID,
    svc: ChromaService = Depends(get_chroma_svc)
):
    """
    Retrieve the documents associated with a particular project in Chroma 

    TODO: Allow for specification of a particular source_type (i.e DOCS or CODE)
    """

    try:
        return svc.delete_collection(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  


@router.delete("/collection/{project_id}/documents")
def delete_documents_from_collections(

    project_id: UUID, 
    delete_collection_docs: DeleteCollectionDocsRequest,
    svc: ChromaService = Depends(get_chroma_svc)
):
    """
    Delete specific documents from existing collection

    TODO: Allow for specification of a particular source_type (i.e DOCS or CODE)
    """

    try:
        return svc.delete_collection_documents(delete_collections=delete_collection_docs, project_id=project_id) 
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )  