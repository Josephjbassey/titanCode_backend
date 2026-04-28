import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.payment_service import PaymentService
from app.db.models import Project

@pytest.mark.asyncio
async def test_process_successful_payment_success():
    db_session = AsyncMock()
    
    # Mock context manager for session.begin()
    begin_mock = AsyncMock()
    begin_mock.__aenter__ = AsyncMock(return_value=None)
    begin_mock.__aexit__ = AsyncMock(return_value=None)
    db_session.begin.return_value = begin_mock
    
    mock_project = MagicMock(spec=Project)
    mock_project.id = 1
    mock_project.status = "in_progress"
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_project
    db_session.execute.return_value = mock_result
    
    await PaymentService.process_successful_payment(1, db_session)
    
    # Verify status changed
    assert mock_project.status == "completed"

@pytest.mark.asyncio
async def test_process_successful_payment_already_completed():
    db_session = AsyncMock()
    
    # Mock context manager for session.begin()
    begin_mock = AsyncMock()
    begin_mock.__aenter__ = AsyncMock(return_value=None)
    begin_mock.__aexit__ = AsyncMock(return_value=None)
    db_session.begin.return_value = begin_mock
    
    mock_project = MagicMock(spec=Project)
    mock_project.id = 1
    mock_project.status = "completed"
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_project
    db_session.execute.return_value = mock_result
    
    await PaymentService.process_successful_payment(1, db_session)
    
    # Status should remain completed, nothing else should change
    assert mock_project.status == "completed"

@pytest.mark.asyncio
async def test_process_successful_payment_not_found():
    db_session = AsyncMock()
    
    begin_mock = AsyncMock()
    begin_mock.__aenter__ = AsyncMock(return_value=None)
    begin_mock.__aexit__ = AsyncMock(return_value=None)
    db_session.begin.return_value = begin_mock
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    db_session.execute.return_value = mock_result
    
    # Should not raise any exception, simply logs and returns
    await PaymentService.process_successful_payment(999, db_session)
