# tests/conftest.py

"""
Shared pytest fixtures for contextualized backend tests.

Fixtures are automatically available to all test modules.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


# ============================================================
# Database Fixtures
# ============================================================

@pytest.fixture
def mock_db_session():
    """
    Mock AsyncSession that doesn't connect to a real database.
    
    Usage: Inject as parameter in any test that needs DB access.
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


# ============================================================
# Service Mocks
# ============================================================

@pytest.fixture
def mock_chroma_service():
    """Mock ChromaService for tests that don't need real vector DB."""
    chroma_svc = MagicMock()
    chroma_svc.get_real_chroma_collection = MagicMock(return_value=MagicMock())
    return chroma_svc


@pytest.fixture
def mock_record_lock_service():
    """Mock RecordLockService - defaults to successful lock acquisition."""
    lock_svc = AsyncMock()
    lock_svc.lock = AsyncMock(return_value=True)
    lock_svc.unlock = AsyncMock(return_value=True)
    return lock_svc


# ============================================================
# Service Instances (with mocked dependencies)
# ============================================================

@pytest.fixture
def ingestion_job_service(mock_db_session, mock_chroma_service, mock_record_lock_service):
    """IngestionJobService with all dependencies mocked."""
    from app.services.ingestion_job import IngestionJobService
    return IngestionJobService(
        db=mock_db_session,
        chroma_svc=mock_chroma_service,
        record_lock_svc=mock_record_lock_service
    )


@pytest.fixture
def file_service(mock_db_session, mock_chroma_service):
    """FileService with all dependencies mocked."""
    from app.services.file import FileService
    return FileService(
        db_session=mock_db_session,
        chroma_svc=mock_chroma_service
    )


# ============================================================
# Test Data Factories
# ============================================================

@pytest.fixture
def sample_data_source():
    """Factory for creating test DataSource objects."""
    def _create(provider="GitHub", url="https://github.com/test/repo"):
        from app.models import DataSource
        ds = MagicMock(spec=DataSource)
        ds.id = uuid4()
        ds.provider = provider
        ds.url = url
        ds.project_data = []
        return ds
    return _create


@pytest.fixture  
def sample_project():
    """Factory for creating test Project objects."""
    def _create(name="Test Project"):
        from app.models import Project
        project = MagicMock(spec=Project)
        project.id = uuid4()
        project.project_name = name
        project.chroma_collection = []
        return project
    return _create