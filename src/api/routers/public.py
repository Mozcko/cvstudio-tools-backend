from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.models.cv import CV
from src.models.public_link import LinkView, PublicLink
from src.models.user import User
from src.schemas.link_schemas import PublicCV, ViewIn
from src.services.pro import apply_expiry
from src.services.public_links import (
    find_public_link,
    is_bot,
    public_content,
    referrer_host,
    served_link_ids,
    visitor_id,
)

# No authentication on these routes: they are what the public page is built from
router = APIRouter(prefix="/public", tags=["Public"])

# The same visitor reloading a page is one view
DEDUPE_WINDOW = timedelta(minutes=30)

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _online_link(slug: str, db: AsyncSession) -> tuple[PublicLink, User]:
    """The link and its owner when the page is online; 404 in every other case, alike."""
    link = await find_public_link(db, slug=slug)
    if not link or not link.is_active:
        raise NOT_FOUND
    owner = (await db.execute(select(User).where(User.id == link.user_id))).scalar_one_or_none()
    if not owner:
        raise NOT_FOUND
    # A pass that ran out since the owner last signed in must not keep extra links online
    apply_expiry(owner)
    if link.id not in await served_link_ids(db, owner):
        raise NOT_FOUND
    return link, owner


@router.get("/cv/{slug}", response_model=PublicCV)
async def read_public_cv(slug: str, response: Response, db: AsyncSession = Depends(get_db)):
    link, owner = await _online_link(slug, db)
    cv = (await db.execute(select(CV).where(CV.id == link.cv_id))).scalar_one_or_none()
    if not cv:
        raise NOT_FOUND

    # Switching a link off, or hiding a phone number, should take effect quickly
    response.headers["Cache-Control"] = "public, max-age=60"
    return PublicCV(
        slug=link.slug,
        title=cv.title,
        language=cv.language,
        theme=cv.theme,
        content=public_content(cv.content, link.show_email, link.show_phone),
        badge=not owner.is_pro,
        indexable=link.indexable,
        updated_at=cv.updated_at,
    )


def _client_ip(request: Request) -> str:
    # Behind the platform's proxy the visitor is the first forwarded address
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "")


@router.post("/cv/{slug}/view", status_code=status.HTTP_204_NO_CONTENT)
async def record_view(slug: str, request: Request, body: ViewIn | None = None, db: AsyncSession = Depends(get_db)):
    """Counts one visit. Stores no IP address and no full referrer."""
    link, _ = await _online_link(slug, db)

    user_agent = request.headers.get("user-agent", "")
    if is_bot(user_agent):
        return

    visitor = visitor_id(_client_ip(request), user_agent, link.id)
    recent = await db.execute(
        select(LinkView.id)
        .where(
            LinkView.link_id == link.id,
            LinkView.visitor == visitor,
            LinkView.viewed_at >= datetime.now(UTC) - DEDUPE_WINDOW,
        )
        .limit(1)
    )
    if recent.first():
        return

    db.add(LinkView(link_id=link.id, visitor=visitor, referrer_host=referrer_host(body.referrer if body else None)))
    await db.commit()
