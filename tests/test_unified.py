import pytest
from unittest.mock import patch, MagicMock
from cozy_memory.unified import CozyMemory, RateLimitExceeded
from cozy_memory.libsql_store import Entity

def test_store_rate_limit_allowed():
    mem = CozyMemory()
    mem.libsql = MagicMock()
    mem.sync = MagicMock()

    mock_entity = Entity(id="test1", type="project", name="test1", description="", metadata={}, created_at="", updated_at="", salience=0.0)
    mem.libsql.upsert_entity.return_value = mock_entity

    with patch('time.time', return_value=100.0):
        # We can call it up to 10 times because limit=10
        for i in range(10):
            result = mem.store(f"test{i}", type="project")
            assert result == mock_entity

def test_store_rate_limit_exceeded():
    mem = CozyMemory()
    mem.libsql = MagicMock()
    mem.sync = MagicMock()

    mock_entity = Entity(id="test", type="project", name="test", description="", metadata={}, created_at="", updated_at="", salience=0.0)
    mem.libsql.upsert_entity.return_value = mock_entity

    with patch('time.time', return_value=100.0):
        # First exhaust the limit
        for i in range(10):
            mem.store(f"test{i}", type="project")

        # The 11th call should raise the exception
        with pytest.raises(RateLimitExceeded) as exc_info:
            mem.store("test11", type="project")

        assert "Rate limit exceeded" in str(exc_info.value)

def test_store_rate_limit_window_expiry():
    mem = CozyMemory()
    mem.libsql = MagicMock()
    mem.sync = MagicMock()

    mock_entity = Entity(id="test", type="project", name="test", description="", metadata={}, created_at="", updated_at="", salience=0.0)
    mem.libsql.upsert_entity.return_value = mock_entity

    with patch('time.time', return_value=100.0):
        # First exhaust the limit
        for i in range(10):
            mem.store(f"test{i}", type="project")

        # Verify it raises
        with pytest.raises(RateLimitExceeded):
            mem.store("test11", type="project")

    # Move time forward by more than 60 seconds (the window)
    with patch('time.time', return_value=200.0):
        # This should succeed since the old calls (at t=100) are expired
        result = mem.store("test_new", type="project")
        assert result == mock_entity
