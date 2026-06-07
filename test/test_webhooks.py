import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from src.main import app
from src.api.dependencies import get_db

@pytest.mark.asyncio
async def test_clerk_user_deleted_webhook():
    """
    Integration test to verify that the Clerk 'user.deleted' webhook 
    responds correctly and triggers database cleanup logic.
    """
    # 1. Create a mock database session
    mock_db = AsyncMock()
    
    # 2. Override the dependency
    app.dependency_overrides[get_db] = lambda: mock_db

    # 3. Simulate Clerk Webhook Payload
    clerk_payload = {
        "type": "user.deleted",
        "data": {
            "id": "user_2N6W4u3..."
        }
    }

    # 4. Send request using httpx AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/webhooks/clerk", json=clerk_payload)

    # 5. Assertions
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    
    # Verify that delete was called (at least once for CVs and once for Users)
    assert mock_db.execute.called
    assert mock_db.commit.called

    # Clean up overrides
    app.dependency_overrides.clear()
