from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

from app.llm import LLMManager
from ..svc_deps import get_async_query_svc

from app.services.query import QueryService
from app.pydantic.query import QueryRequest

import logging
from datetime import datetime

router = APIRouter(prefix="/query")

logger = logging.getLogger(__name__)

@router.post("/", summary="One-time querying of a specified Project's ingested Documentation & Code")
async def query(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    svc: QueryService = Depends(get_async_query_svc)
):
    """
    Perform a one-time query against the ingested documentation and code for a specified Project.
    """

    try:
        start_time = datetime.now()
        logger.info(f"Received query request for project_id={request.project_id} with query='{request.query}' at {start_time}")

        # create inital query record 
        q_and_a_record = await svc.q_and_a_svc.init_q_and_a_record(request.project_id, request.query, start_time)

        # NOTE: For sake of this endpoint, we'll simply use the default LLM configurations (conversations will be configured on a per LLM basis)
        llm_manager = LLMManager()

        background_tasks.add_task(svc.execute_q_and_a_query, request.query, request.project_id, q_and_a_record.id, q_and_a_record.start_time, llm_manager)

        return {
            "id": q_and_a_record.id,
            "status": q_and_a_record.status,
            "start_time": start_time,
            "question": q_and_a_record.question
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
