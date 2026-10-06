import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from svix.webhooks import Webhook

from src.core.config import settings
from src.models.cv import CV
from src.models.user import User

USER = "user_2N6W4u3"


def signed(payload: dict, secret: str = None):
    """Body and headers exactly as Svix (Clerk's webhook transport) would send them."""
    body = json.dumps(payload)
    msg_id = "msg_test_1"
    timestamp = datetime.now(timezone.utc)
    signature = Webhook(secret or settings.CLERK_WEBHOOK_SECRET).sign(msg_id, timestamp, body)
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature,
        "content-type": "application/json",
    }
    return body, headers


async def seed_user_with_cv(db):
    db.add(User(id=USER, is_pro=True))
    await db.flush()
    db.add(CV(user_id=USER, title="CV", content={}))
    await db.commit()


async def count(db, model):
    return (await db.execute(select(func.count()).select_from(model))).scalar()


async def test_unsigned_request_is_rejected_and_deletes_nothing(client, db):
    await seed_user_with_cv(db)
    payload = {"type": "user.deleted", "data": {"id": USER}}

    response = await client.post("/api/v1/webhooks/clerk", json=payload)

    assert response.status_code == 400
    assert await count(db, User) == 1
    assert await count(db, CV) == 1


async def test_wrong_secret_is_rejected(client, db):
    await seed_user_with_cv(db)
    body, headers = signed(
        {"type": "user.deleted", "data": {"id": USER}},
        secret="whsec_c2VjcmV0X3RoYXRfaXNfbm90X291cnM=",
    )

    response = await client.post("/api/v1/webhooks/clerk", content=body, headers=headers)

    assert response.status_code == 400
    assert await count(db, User) == 1


async def test_tampered_body_is_rejected(client, db):
    await seed_user_with_cv(db)
    _, headers = signed({"type": "user.updated", "data": {"id": "someone_else"}})
    tampered = json.dumps({"type": "user.deleted", "data": {"id": USER}})

    response = await client.post("/api/v1/webhooks/clerk", content=tampered, headers=headers)

    assert response.status_code == 400
    assert await count(db, User) == 1


async def test_signed_user_deleted_purges_data(client, db):
    await seed_user_with_cv(db)
    body, headers = signed({"type": "user.deleted", "data": {"id": USER}})

    response = await client.post("/api/v1/webhooks/clerk", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert await count(db, User) == 0
    assert await count(db, CV) == 0


async def test_user_created_stores_primary_email(client, db):
    body, headers = signed({
        "type": "user.created",
        "data": {
            "id": USER,
            "primary_email_address_id": "idn_2",
            "email_addresses": [
                {"id": "idn_1", "email_address": "old@example.com"},
                {"id": "idn_2", "email_address": "jane@example.com"},
            ],
        },
    })

    response = await client.post("/api/v1/webhooks/clerk", content=body, headers=headers)

    assert response.status_code == 200
    user = (await db.execute(select(User).where(User.id == USER))).scalar_one()
    assert user.email == "jane@example.com"
    assert user.is_pro is False
