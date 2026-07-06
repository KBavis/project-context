from __future__ import annotations

import logging
from uuid import UUID
from abc import abstractmethod

from app.models import DataSource
from app.services.file import FileService
from app.models.data_source import DataSourceType
from app.data_providers import DataProvider
from pathlib import Path
from io import BytesIO


class IngestibleDataProvider(DataProvider):
    
    # DataSource types that can be embedded/ingested by an IngestibleDataProvider
    INGESTIBLE_TYPES: frozenset[DataSourceType] = frozenset({
        DataSourceType.REPOSITORY,
        DataSourceType.DOCUMENTATION,
    })
    
    def __init__(
        self, 
        data_source: DataSource
    ) -> None:
        super().__init__(data_source=data_source)
        self.file_svc: FileService | None = None
        self.embed_task_id: UUID | None = None
        
    @classmethod
    def is_ingestible(cls, data_source: DataSource) -> bool:
        """Return True if the DataSource can be embedded by an IngestibleDataProvider."""
        return data_source.type in cls.INGESTIBLE_TYPES

    @classmethod
    def from_provider(cls, data_source: DataSource) -> IngestibleDataProvider:
        match data_source.type:
            case DataSourceType.REPOSITORY:
                from app.data_providers.ingestible.repository.base import RepositoryDataProvider
                return RepositoryDataProvider.from_provider(data_source)
            case DataSourceType.DOCUMENTATION:
                from app.data_providers.ingestible.documentation.base import DocumentationDataProvider
                return DocumentationDataProvider.from_provider(data_source)
            case _:
                raise Exception(
                    f"Data Source type {data_source.type} is not configured as an Ingestible Data Provider"
                )
    
    @abstractmethod
    async def ingest_data(self, embed_task_id: UUID, file_svc: "FileService", touched_file_paths: list[str] | None = None):
        raise NotImplementedError()

        
    @abstractmethod
    async def view_file(self, file_path: str) -> str:
        """
        Functionality to extract exact file contents from a particular path 
        This function will end up being an internal tool that we can leverage in our "research" phase of 
        our Agentic Worfklow 

        Args:
            file_path (str): The absolute path to the file to view 
        """
        raise NotImplementedError()

    @abstractmethod
    async def list_directory(self, path: str) -> str:
        """
        Functionality to list the contents of a particular directory 
        This function will end up being an internal tool that we can leverage in our "research" phase of 
        our Agentic Worfklow 

        NOTE: Instead of having some massive "view_project_strucutre" tool, we can just use 
        the "list_directory" function based on retrieved files from our key word / sematnic search

        Args:
            path (str): The absolute path to the directory to list the contents of 
        """
        raise NotImplementedError()

    def list_directory_description(self) -> str:
        """
        The description exposed to the LLM for this provider's `list_directory` tool.
        Providers whose `list_directory` uses non-filesystem addressing (e.g. Confluence
        page IDs) override this so the agent supplies the right argument shape.
        """
        ds = self.data_source
        return (
            f"List the contents of a directory in DataSource '{ds.name}' ({ds.type}): {ds.provider}.\n"
            "The path argument MUST begin with a '/' unless listing the root directory. \n"
            "To list the root directory, pass an empty string ''.\n"
            "To list a subdirectory like 'docs', pass '/docs' (NOT 'docs/' or 'docs')."
        )

    def line_anchor(self, start_line: int, end_line: int) -> str:
        """
        URL fragment that deep-links to a line range. Default is GitHub-style (`#L10-L25`).
        Providers with a different scheme (e.g. Bitbucket) override this.
        """
        return f"#L{start_line}-L{end_line}"

    def view_file_description(self) -> str:
        """
        The description exposed to the LLM for this provider's `view_file` tool.
        Providers whose files aren't addressed by a filesystem path (e.g. Confluence pages,
        addressed by numeric ID) override this so the agent supplies the right argument shape.
        """
        ds = self.data_source
        return (
            f"View the full contents of a file in DataSource '{ds.name}' ({ds.type}: {ds.provider}). "
            "For standard text and code files, this retrieves their contents directly. "
            "Code files are returned with each line prefixed by its line number (e.g. '42: <code>') "
            "so you can cite exact line ranges — use these numbers for the finding's `source` range, "
            "and never copy the 'N: ' prefix into any code you quote. "
            "For PDF files (.pdf), this automatically retrieves the parsed plain text chunks sequentially "
            "from our document store, avoiding binary file downloads. "
            "The file_path argument must NOT begin with a '/'. If the file is in the root directory, pass the "
            "filename (e.g., 'compose.yaml'). If it is in a subdirectory, pass the relative path (e.g., 'sub_dir/filename.extension')."
        )

    def _write_file(self, full_path: Path, buffer: BytesIO):
        """Sync helper: write buffered content to disk (runs in worker thread)."""
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(buffer.getbuffer())

    async def generate_citation(self, file_path: str) -> str: 
        """
        Generates a citation for a given file path 

        Args:
            file_path (str): The absolute path to the file to generate a citation for 
        
        Returns:
            str: The citation for the file
        """
        raise NotImplementedError()