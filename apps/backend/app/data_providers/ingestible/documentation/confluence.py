from __future__ import annotations
import logging
import re
import asyncio
import httpx
from uuid import UUID
from pathlib import Path
from io import BytesIO
import tempfile
import base64
import os

from docling.document_converter import DocumentConverter

from .base import DocumentationDataProvider
from app.core import settings
from app.pydantic import DocsFileExtension, File, FileProcesingStatus
from app.models.data_source import DataSource
from app.services.file import FileService

logger = logging.getLogger(__name__)

class ConfluenceDataProvider(DocumentationDataProvider):

    def __init__(self, data_source: DataSource):
        super().__init__(data_source)

    def _parse_documentation_ref(self):
        # Format: https://<domain>/spaces/<SPACE_KEY>/pages/<PAGE_ID>[/<Title>]
        parsed = self.url.rstrip("/").split("/")
        try:
            spaces_idx = parsed.index("spaces")
            self.space_key = parsed[spaces_idx + 1]
            pages_idx = parsed.index("pages")
            self.root_page_id = parsed[pages_idx + 1]
            self.domain = parsed[2]
        except ValueError:
            raise Exception(f"URL {self.url} does not match expected Confluence format: https://<domain>/spaces/<SPACE_KEY>/pages/<PAGE_ID>")

    def _construct_base_urls(self):
        self._parse_documentation_ref()
        self.base_url = f"https://{self.domain}/spaces/{self.space_key}/pages/"
        self.base_api_url = f"https://{self.domain}/rest/api/content"

    def _get_request_headers(self) -> dict[str, str] | None:
        if settings.CONFLUENCE_EMAIL and settings.CONFLUENCE_SECRET_TOKEN:
            auth_str = f"{settings.CONFLUENCE_EMAIL}:{settings.CONFLUENCE_SECRET_TOKEN}"
            b64_auth_str = base64.b64encode(auth_str.encode()).decode()
            return {"Authorization": f"Basic {b64_auth_str}"}
        elif settings.CONFLUENCE_SECRET_TOKEN:
            # Atlassian Server/DC Personal Access Tokens authenticate via Bearer.
            return {"Authorization": f"Bearer {settings.CONFLUENCE_SECRET_TOKEN}"}
        return None

    def _validate_url(self):
        if "/spaces/" not in self.url or "/pages/" not in self.url:
            raise Exception(
                f"The specified data source URL, {self.url}, is not in the proper format: https://<domain>/spaces/<SPACE_KEY>/pages/<PAGE_ID>"
            )

    async def ingest_data(self, file_svc: FileService, job_pk: UUID):
        self.file_svc = file_svc
        self.job_pk = job_pk
        self.new_or_modified_file_ids = []

        if not self.file_svc or not self.job_pk:
            raise Exception("FileService and JobPK not provided when attempting to ingest data")

        # Download root page and its children recursively
        await self._get_page_tree(self.root_page_id)

        # Cleanup
        await self.file_svc.cleanup(self.data_source.id, self.job_pk, self.new_or_modified_file_ids)

    async def _get_page_tree(self, page_id: str):
        # 1. Download current page
        # Get page info
        try:
            page_url = f"{self.base_api_url}/{page_id}"
            async with httpx.AsyncClient() as client:
                response = await client.get(page_url, headers=self.request_headers)
                response.raise_for_status()
                page_data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch page metadata for {page_id}")
            raise e

        title = page_data.get("title", f"page_{page_id}")
        await self._download_page(page_id, title)

        # 2. Get children
        try:
            children_url = f"{self.base_api_url}/{page_id}/child/page"
            async with httpx.AsyncClient() as client:
                response = await client.get(children_url, headers=self.request_headers)
                response.raise_for_status()
                children_data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch children for {page_id}")
            raise e

        for child in children_data.get("results", []):
            child_id = child["id"]
            await self._get_page_tree(child_id)

    async def _download_page(self, page_id: str, title: str):
        assert self.file_svc and self.job_pk

        # Safe filename
        safe_title = "".join(c if c.isalnum() else "_" for c in title)
        file_name = f"{safe_title}_{page_id}.md"
        file_path = f"confluence/{file_name}"
        
        try:
            # Fetch page content in storage format
            content_url = f"{self.base_api_url}/{page_id}?expand=body.storage"
            async with httpx.AsyncClient() as client:
                response = await client.get(content_url, headers=self.request_headers)
                response.raise_for_status()
                content_data = response.json()
                
            html_content = content_data.get("body", {}).get("storage", {}).get("value", "")
            
            if not html_content:
                logger.warning(f"No HTML content found for Confluence page {page_id}")
                return

            # Use Docling to convert HTML storage format to Markdown
            markdown_content = await asyncio.to_thread(self._convert_html_to_markdown, html_content)
            
            # Skip saving if the page has no actual content
            if not markdown_content or not markdown_content.strip():
                logger.info(f"Skipping blank/empty Confluence page: {page_id} ({title})")
                return
            
            buffer = BytesIO(markdown_content.encode("utf-8"))
            
            # Since we have the buffer, compute hash manually instead of downloading response
            buffer.seek(0)
            hashed_content = await asyncio.to_thread(self._hash_buffer, buffer)
            buffer.seek(0)
            
            size = len(buffer.getvalue())
            url = f"{self.base_url}{page_id}"

            file = File(
                path=file_path, 
                file_name=file_name, 
                file_type=DocsFileExtension.MD, 
                size=size, 
                hash=hashed_content,
                file_url=url
            )
            file_status = await self.file_svc.process_file(file, self.data_source, self.job_pk, self.new_or_modified_file_ids)

            if file_status == FileProcesingStatus.UNCHANGED:
                return 

            dir_path = f"{settings.TMP_DOCS}/{self.job_pk}"
            full_path = Path(f"{dir_path}/{file_path}")
            
            await asyncio.to_thread(self._write_file, full_path, buffer)

        except Exception as e:
            logger.error(f"Failure downloading page={page_id} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to download page: {title}", e)

    def _convert_html_to_markdown(self, html_content: str) -> str:
        """
        Converts HTML to Markdown using docling DocumentConverter
        """
        converter = DocumentConverter()
        
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write(html_content)
            temp_path = f.name
            
        try:
            conv_result = converter.convert(temp_path)
            return conv_result.document.export_to_markdown()
        except Exception as e:
            logger.error(f"Docling conversion failed: {str(e)}")
            return ""
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _hash_buffer(self, buffer: BytesIO) -> str:
        import hashlib
        h = hashlib.sha256()
        chunk = buffer.read(8192)
        while chunk:
            h.update(chunk)
            chunk = buffer.read(8192)
        return h.hexdigest()

    async def view_file(self, file_path: str) -> str:
        # File path in this context is "confluence/safe_title_pageId.md"
        # We can extract the pageId and return its markdown content
        try:
            page_id = file_path.split("_")[-1].split(".")[0]
            
            content_url = f"{self.base_api_url}/{page_id}?expand=body.storage"
            async with httpx.AsyncClient() as client:
                response = await client.get(content_url, headers=self.request_headers)
                response.raise_for_status()
                content_data = response.json()
                
            html_content = content_data.get("body", {}).get("storage", {}).get("value", "")
            if not html_content:
                return "No content found."
                
            markdown_content = await asyncio.to_thread(self._convert_html_to_markdown, html_content)
            return markdown_content
            
        except Exception as e:
            logger.error(f"Failure viewing file={file_path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to view file: {file_path}", e)

    async def list_directory(self, path: str) -> str:
        # Since Confluence is a page tree, path could map to a page ID or empty for root
        try:
            page_id = path if path else self.root_page_id
            
            children_url = f"{self.base_api_url}/{page_id}/child/page"
            async with httpx.AsyncClient() as client:
                response = await client.get(children_url, headers=self.request_headers)
                response.raise_for_status()
                children_data = response.json()
                
            path_contents = [f"Children of Page {page_id}:"]
            for child in children_data.get("results", []):
                path_contents.append(f"{child['title']} (ID: {child['id']})")
            
            return "\n".join(path_contents)
            
        except Exception as e:
            logger.error(f"Failure listing directory={path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to list directory: {path}", e)

    async def generate_citation(self, path: str) -> str:
        # Path format: confluence/safe_title_pageId.md
        try:
            page_id = path.split("_")[-1].split(".")[0]
            url = f"{self.base_url}{page_id}"
            return f"[{path}]({url})"
        except Exception as e:
            logger.error(f"Failure generating citation for path={path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to generate citation for path: {path}", e)
