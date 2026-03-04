from app.models import Citation
from app.pydantic import FileCitation 
from app.services.files import FileService

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class CitationService:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.file_svc: FileService = FileService(db)
    


    async def generate_citations(self, chunks: list[NodeWithScore]) -> list[FileCitation]:
        """
        Generate citations based on the utilized chunks.

        Args:
            chunks (list[NodeWithScore]): The chunks utilized in the query response.

        Returns:
            list[FileCitation]: A list of file citations.
        """
        citations = []
        seen_ids = set() 
        for chunk in chunks:
            
            # extract file ID from chunk
            file_id = chunk.metadata.get("file_id", None)
            if not file_id:
                logger.warning(f"No file ID found for chunk {chunk.id_}, skipping Citation generation")
                continue
            
            # get file by specified file ID corresponding to chunk 
            file = await self.file_svc.get_file_by_id(file_id)
            if not file:
                logger.warning(f"No file found for file ID {file_id}, skipping Citation generation")
                continue
            
            if file_id in seen_ids:
                logger.debug(f"Skipping duplicate file ID {file_id}")
                continue

            seen_ids.add(file_id)
            citations.append(FileCitation(
                file_url=file.file_url,
                file_id=str(file.id),
                file_name=file.name,
                data_source_id=str(file.data_source_id)
            ))

        logger.debug(f"Generated citations: {citations}") 
        return citations
    

    async def get_citations(self, conversation_id: UUID) -> list[Citation]:
        """
        Get citations for a specific conversation.

        Args:
            conversation_id (UUID): The ID of the conversation.

        Returns:
            list[Citation]: A list of citations.
        """
        stmt = (
            select(Citation)
            .join(Citation.message)
            .where(Message.conversation_id == conversation_id)
        )
        res = await self.db.execute(stmt)

        citations = res.scalars().all()
        logger.debug(f"Fetched following Citations for Conversation={conversation_id}: {citations}")
        return citations

    

    async def save_citations(self, citations: list[Citation], message_id: UUID):
        """
        Save citations for a specific conversation.

        Args:
            citations (list[Citation]): A list of citations.
        """
        logger.debug(f"Saving Citations: {citations}")

        records_to_save = [self.map_to_record(citation, message_id) for citation in citations]

        self.db.add_all(records_to_save)
        await self.db.commit() 
    

    async def map_to_record(self, citation: FileCitation, message_id: UUID) -> Citation:
        """
        Map a FileCitation to a Citation record.

        Args:
            citation (FileCitation): The citation to map.
            message_id (UUID): The ID of the message.

        Returns:
            Citation: The mapped citation.
        """

        return Citation(
            file_id=citation.file_id,
            message_id=message_id
        )
