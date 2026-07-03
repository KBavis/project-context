from __future__ import annotations
from abc import abstractmethod
from uuid import UUID

from app.data_providers.ingestible.base import IngestibleDataProvider
from app.data_providers import Provider
from app.models.data_source import DataSource
from app.services.file import FileService

class DocumentationDataProvider(IngestibleDataProvider):
    """
    Abstract base class for Documentation data providers (like Confluence, Notion, etc).
    Contains methods specific to pulling page trees and converting them to readable formats.
    """

    def __init__(self, data_source: DataSource):
        super().__init__(data_source=data_source)

        # construct required URLs
        self._construct_base_urls()

    @classmethod
    def from_provider(cls, data_source: DataSource) -> DocumentationDataProvider:
        match data_source.provider:
            case Provider.CONFLUENCE:
                from app.data_providers.ingestible.documentation.confluence import ConfluenceDataProvider
                return ConfluenceDataProvider(data_source=data_source)
            case _:
                raise Exception(f"Data Source provider {data_source.provider} is not configured as a Documentation Data Provider")

    @abstractmethod
    def _parse_documentation_ref(self):
        """
        Extract relevant context from the provided Data Source URL
        """
        raise NotImplementedError()
    
    @abstractmethod
    def _construct_base_urls(self):
        """
        Construct the base URLs for the documentation provider.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def _get_page_tree(self, curr_url: str, file_svc: FileService, embed_task_id: UUID):
        """
        Recursively pull down the documentation page tree.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def _download_page(self, page_id: str, title: str, file_svc: FileService, embed_task_id: UUID):
        """
        Download a page and save it as Markdown.
        """
        raise NotImplementedError()
