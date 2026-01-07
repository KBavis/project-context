from fastapi import APIRouter, Depends, HTTPException, status
from ..svc_deps import get_async_query_svc

from app.services.query import QueryService
from app.pydantic.query import QueryRequest

router = APIRouter(prefix="/query")

@router.post("/", summary="One-time querying of a specified Project's ingested Documentation & Code")
async def query(
    request: QueryRequest,
    svc: QueryService = Depends(get_async_query_svc)
):
    """
    Perform a one-time query against the ingested documentation and code for a specified Project.
    """
    try:
        # TODO: Run this as a background task in order to give user fast response and avoid timeouts
        response = await svc.execute_simple_query(request.query, request.project_id)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
