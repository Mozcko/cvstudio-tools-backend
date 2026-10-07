import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user_obj, get_db
from src.core.config import settings
from src.models.cv import CV
from src.models.public_link import LinkView, PublicLink
from src.models.user import User
from src.schemas.link_schemas import DailyViews, LinkOut, LinkStats, LinkWrite, ReferrerViews, SlugCheck
from src.services.public_links import normalize_slug, served_link_ids, slug_problem

router = APIRouter(tags=["Public links"])

STATS_DAYS = 30
TOP_REFERRERS = 5

FREE_LINK_LIMIT_DETAIL = "Free plan allows one public link. Upgrade to Pro to share more CVs."
SLUG_DETAILS = {
    "length": "The name must be between 3 and 40 characters.",
    "format": "Use lowercase letters, numbers and single hyphens, without a hyphen at either end.",
    "reserved": "That name is not available.",
}


async def _own_cv(cv_id: uuid.UUID, user: User, db: AsyncSession) -> CV:
    cv = (await db.execute(select(CV).where(CV.id == cv_id, CV.user_id == user.id))).scalar_one_or_none()
    if not cv:
        # Also what someone else's CV looks like
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")
    return cv


async def _link_of(cv_id: uuid.UUID, user: User, db: AsyncSession) -> PublicLink:
    await _own_cv(cv_id, user, db)
    link = (await db.execute(select(PublicLink).where(PublicLink.cv_id == cv_id))).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This CV has no public link")
    return link


async def _view_counts(db: AsyncSession, links: list[PublicLink]) -> dict[uuid.UUID, tuple[int, int]]:
    """(total views, views since the owner last looked) per link."""
    if not links:
        return {}
    result = await db.execute(
        select(
            LinkView.link_id,
            func.count(),
            func.sum(
                case(
                    (PublicLink.views_seen_at.is_(None), 1),
                    (LinkView.viewed_at > PublicLink.views_seen_at, 1),
                    else_=0,
                )
            ),
        )
        .join(PublicLink, PublicLink.id == LinkView.link_id)
        .where(LinkView.link_id.in_([link.id for link in links]))
        .group_by(LinkView.link_id)
    )
    return {link_id: (total, int(new or 0)) for link_id, total, new in result}


def _out(link: PublicLink, served: set, counts: dict) -> LinkOut:
    total, new = counts.get(link.id, (0, 0))
    return LinkOut(
        cv_id=link.cv_id,
        slug=link.slug,
        is_active=link.is_active,
        paused=link.is_active and link.id not in served,
        show_email=link.show_email,
        show_phone=link.show_phone,
        indexable=link.indexable,
        views_total=total,
        views_new=new,
        created_at=link.created_at,
    )


@router.get("/links", response_model=list[LinkOut])
async def list_links(user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PublicLink).where(PublicLink.user_id == user.id).order_by(PublicLink.created_at, PublicLink.id)
    )
    links = list(result.scalars())
    served = await served_link_ids(db, user)
    counts = await _view_counts(db, links)
    return [_out(link, served, counts) for link in links]


@router.get("/links/check", response_model=SlugCheck)
async def check_slug(
    slug: str = Query(max_length=80),
    cv_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    """Whether a name can be used (for the CV given, which may already hold it)."""
    name = normalize_slug(slug)
    problem = slug_problem(name)
    if problem:
        return SlugCheck(slug=name, available=False, reason=problem)
    holder = (await db.execute(select(PublicLink).where(PublicLink.slug == name))).scalar_one_or_none()
    taken = holder is not None and not (holder.user_id == user.id and holder.cv_id == cv_id)
    return SlugCheck(slug=name, available=not taken, reason="taken" if taken else None)


@router.post("/links/seen", status_code=status.HTTP_204_NO_CONTENT)
async def mark_views_seen(user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    """The owner has looked at their statistics: later views count as new."""
    await db.execute(update(PublicLink).where(PublicLink.user_id == user.id).values(views_seen_at=datetime.now(UTC)))
    await db.commit()


@router.put("/cvs/{cv_id}/link", response_model=LinkOut)
async def save_link(
    cv_id: uuid.UUID,
    body: LinkWrite,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    """Publishes a CV, or changes how it is published."""
    await _own_cv(cv_id, user, db)

    slug = normalize_slug(body.slug)
    problem = slug_problem(slug)
    if problem:
        raise HTTPException(status_code=422, detail=SLUG_DETAILS[problem])

    link = (await db.execute(select(PublicLink).where(PublicLink.cv_id == cv_id))).scalar_one_or_none()

    if body.is_active and not user.is_pro:
        others = await db.execute(
            select(func.count())
            .select_from(PublicLink)
            .where(PublicLink.user_id == user.id, PublicLink.is_active.is_(True), PublicLink.cv_id != cv_id)
        )
        if others.scalar_one() >= settings.FREE_PUBLIC_LINK_LIMIT:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FREE_LINK_LIMIT_DETAIL)

    if link is None:
        link = PublicLink(id=uuid.uuid4(), cv_id=cv_id, user_id=user.id, created_at=datetime.now(UTC))
        db.add(link)
    link.slug = slug
    link.is_active = body.is_active
    link.show_email = body.show_email
    link.show_phone = body.show_phone
    link.indexable = body.indexable

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That name is already taken.") from None

    served = await served_link_ids(db, user)
    counts = await _view_counts(db, [link])
    return _out(link, served, counts)


@router.delete("/cvs/{cv_id}/link", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(cv_id: uuid.UUID, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    """Removes the link and its statistics; the name becomes available again."""
    await db.delete(await _link_of(cv_id, user, db))
    await db.commit()


@router.get("/cvs/{cv_id}/link/stats", response_model=LinkStats)
async def link_stats(cv_id: uuid.UUID, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    link = await _link_of(cv_id, user, db)

    totals = await db.execute(
        select(func.count(), func.count(func.distinct(LinkView.visitor))).where(LinkView.link_id == link.id)
    )
    views_total, visitors_total = totals.one()
    stats = LinkStats(views_total=views_total, visitors_total=visitors_total)
    if not user.is_pro:
        return stats

    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=STATS_DAYS - 1)
    day = func.date(func.timezone("UTC", LinkView.viewed_at))
    per_day = await db.execute(
        select(day, func.count())
        .where(
            LinkView.link_id == link.id,
            LinkView.viewed_at >= datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC),
        )
        .group_by(day)
    )
    counted = dict(per_day.all())
    # Every day of the window, also the ones without visits, so a chart needs no gap filling
    stats.daily = [
        DailyViews(day=first_day + timedelta(days=offset), views=counted.get(first_day + timedelta(days=offset), 0))
        for offset in range(STATS_DAYS)
    ]

    referrers = await db.execute(
        select(LinkView.referrer_host, func.count().label("views"))
        .where(LinkView.link_id == link.id)
        .group_by(LinkView.referrer_host)
        .order_by(func.count().desc(), LinkView.referrer_host)
        .limit(TOP_REFERRERS)
    )
    stats.referrers = [ReferrerViews(host=host, views=views) for host, views in referrers]
    return stats
