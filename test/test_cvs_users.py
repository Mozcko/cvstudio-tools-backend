import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.models.user import User

CONTENT = {"personal": {"name": "Jane"}, "experience": []}


async def create_cv(client, title="CV", **extra):
    return await client.post("/api/v1/cvs/", json={"title": title, "content": CONTENT, **extra})


async def test_me_creates_user_and_hides_internal_fields(client):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200
    assert response.json() == {"id": "user_test_1", "is_pro": False, "pro_expires_at": None}


async def test_me_applies_expiry(client, db):
    db.add(User(id="user_test_1", is_pro=True,
                pro_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    await db.commit()

    response = await client.get("/api/v1/users/me")

    assert response.json()["is_pro"] is False


async def test_cv_crud_with_theme(client):
    created = await create_cv(client, theme="modern", language="EN", id="ignored-client-id")
    assert created.status_code == 201
    cv = created.json()
    assert cv["theme"] == "modern" and cv["language"] == "EN"
    assert cv["id"] != "ignored-client-id"

    updated = await client.put(f"/api/v1/cvs/{cv['id']}", json={"theme": "minimal", "title": "New"})
    assert updated.json()["theme"] == "minimal"
    assert updated.json()["title"] == "New"
    assert updated.json()["content"] == CONTENT

    fetched = await client.get(f"/api/v1/cvs/{cv['id']}")
    assert fetched.json()["theme"] == "minimal"

    assert (await client.delete(f"/api/v1/cvs/{cv['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/cvs/{cv['id']}")).status_code == 404


async def test_list_is_newest_first(client):
    first = (await create_cv(client, "first")).json()
    await asyncio.sleep(0.05)
    await create_cv(client, "second")
    await asyncio.sleep(0.05)
    await client.put(f"/api/v1/cvs/{first['id']}", json={"title": "first-edited"})

    titles = [cv["title"] for cv in (await client.get("/api/v1/cvs/")).json()]

    assert titles == ["first-edited", "second"]


async def test_other_users_cv_is_forbidden(client, current_user):
    cv = (await create_cv(client)).json()

    current_user["id"] = "user_other"

    assert (await client.get(f"/api/v1/cvs/{cv['id']}")).status_code == 403
    assert (await client.put(f"/api/v1/cvs/{cv['id']}", json={"title": "x"})).status_code == 403
    assert (await client.delete(f"/api/v1/cvs/{cv['id']}")).status_code == 403
    assert (await client.get("/api/v1/cvs/")).json() == []


async def test_free_tier_limit(client, db):
    for i in range(3):
        assert (await create_cv(client, f"cv{i}")).status_code == 201

    blocked = await create_cv(client, "cv4")
    assert blocked.status_code == 403
    assert "limit" in blocked.json()["detail"].lower()

    user = (await db.execute(select(User).where(User.id == "user_test_1"))).scalar_one()
    user.is_pro = True
    await db.commit()

    assert (await create_cv(client, "cv4")).status_code == 201
