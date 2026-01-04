"""
Tests for app.services.ingestion_job module.

This module tests the ingestion job service functionality.
"""

import pytest
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock
from app.services.ingestion_job import IngestionJobService
from app.models import RecordType, DataSource
from unittest.mock import MagicMock


class TestIngestionJobService:
    """Tests for IngestionJobService class."""

    @pytest.mark.unit
    async def test_init_ingestion_job(self, ingestion_job_service: IngestionJobService, sample_data_source):
        """
        Test that init_ingestion_job returns a UUID (job_pk) and a DataSource.
        
        This is a unit test, so we mock all external dependencies to isolate the method's behavior.
        """
        # Create a mock data_source using the fixture
        mock_data_source = sample_data_source()
        
        # Create a mock result object for the database query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_data_source
        
        # Mock the database execute to return our mock result
        ingestion_job_service.db.execute = AsyncMock(return_value=mock_result)
        
        # Mock the create_ingestion_job method since we don't want to actually create a job in the DB
        ingestion_job_service.create_ingestion_job = AsyncMock()
        
        # Prepare test inputs
        data_source_id = uuid4()  # Generate a UUID for data_source_id
        job_start_time = datetime.now()  # Current time
        
        # Call the method under test
        actual_data_source, actual_job_pk = await ingestion_job_service.init_ingestion_job(
            data_source_id=data_source_id,
            job_start_time=job_start_time
        )
        
        # Assertions: Check that it returns the expected data_source and a UUID job_pk
        assert actual_data_source == mock_data_source

        # Verify that the mocks were called correctly
        ingestion_job_service.db.execute.assert_called_once()
        ingestion_job_service.record_lock_svc.lock.assert_called_once_with(mock_data_source.id, RecordType.DATA_SOURCE)
        ingestion_job_service.create_ingestion_job.assert_called_once_with(
            job_pk=actual_job_pk,
            data_source_id=data_source_id,
            start_time=job_start_time
        )
