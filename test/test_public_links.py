"""Public CV links (/u/<name>) and their view statistics."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.core.config import settings
from src.models.public_link import LinkView, PublicLink
from src.models.user import User
from src.services.public_links import (
    RESERVED_SLUGS,
    is_bot,
    public_content,
    referrer_host,
    slug_problem,
    visitor_id,
)

API = "/api/v1"
USER = "user_test_1"
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"}
CONTENT = {
    "personal": {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+1 555 0100",
        "city": "Lisbon",
        "summary": "Builds things.",
    },
    "experience": [{"company": "Acme", "role": "Lead"}],
}


async def make_cv(client, title="CV", content=None):
    response = await client.post(f"{API}/cvs/", json={"title": title, "content": content or CONTENT, "theme": "modern"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def publish(client, cv_id, slug="jane-doe", **options):
    return await client.put(f"{API}/cvs/{cv_id}/link", json={"slug": slug, **options})


async def make_pro(db, user_id=USER):
    # Requests change the user in their own sessions; read the row afresh
    query = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    user = (await db.execute(query)).scalar_one_or_none()
    if user:
        user.is_pro = True
        user.pro_expires_at = None
    else:
        db.add(User(id=user_id, is_pro=True))
    await db.commit()


async def view(client, slug, ip="203.0.113.7", agent=None, referrer=None):
    headers = {**BROWSER, "X-Forwarded-For": ip}
    if agent is not None:
        headers["User-Agent"] = agent
    return await client.post(f"{API}/public/cv/{slug}/view", json={"referrer": referrer}, headers=headers)


async def views(db):
    return (await db.execute(select(func.count()).select_from(LinkView))).scalar_one()


# ── Names ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("slug", ["abc", "juan-perez", "ana-2", "x1y", "a" * 40, "7days"])
def test_valid_names(slug):
    assert slug_problem(slug) is None


@pytest.mark.parametrize(
    ("slug", "reason"),
    [
        ("ab", "length"),
        ("a" * 41, "length"),
        ("-abc", "format"),
        ("abc-", "format"),
        ("a--b", "format"),
        ("juan perez", "format"),
        ("juan_perez", "format"),
        ("josé", "format"),
        ("a/b", "format"),
        ("../x", "format"),
        ("admin", "reserved"),
        ("pricing", "reserved"),
        ("sign-in", "reserved"),
        ("api", "reserved"),
    ],
)
def test_invalid_names(slug, reason):
    assert slug_problem(slug) == reason


def test_reserved_names_cover_the_site_paths():
    assert {"app", "pricing", "privacy", "sign-in", "sign-up", "login", "en", "pt", "u", "www"} <= RESERVED_SLUGS


# ── Publishing ────────────────────────────────────────────────────────────────


async def test_publish_and_read_publicly(client, db):
    cv_id = await make_cv(client, title="Backend CV")

    saved = await publish(client, cv_id, slug="  Jane-Doe ")

    assert saved.status_code == 200
    link = saved.json()
    assert (link["slug"], link["is_active"], link["paused"]) == ("jane-doe", True, False)
    assert (link["show_email"], link["show_phone"], link["indexable"]) == (True, False, False)
    assert (link["views_total"], link["views_new"]) == (0, 0)

    public = await client.get(f"{API}/public/cv/JANE-doe")
    assert public.status_code == 200
    assert "max-age" in public.headers["cache-control"]
    body = public.json()
    assert set(body) == {"slug", "title", "language", "theme", "content", "badge", "indexable", "updated_at"}
    assert (body["title"], body["theme"], body["badge"], body["indexable"]) == ("Backend CV", "modern", True, False)
    # Phone hidden by default, e-mail shown; nothing identifies the account
    assert body["content"]["personal"]["email"] == "jane@example.com"
    assert body["content"]["personal"]["phone"] == ""
    assert body["content"]["experience"] == CONTENT["experience"]
    assert USER not in public.text


async def test_contact_details_follow_the_owners_choice(client, db):
    cv_id = await make_cv(client)

    await publish(client, cv_id, show_email=False, show_phone=True)
    personal = (await client.get(f"{API}/public/cv/jane-doe")).json()["content"]["personal"]
    assert (personal["email"], personal["phone"], personal["name"]) == ("", "+1 555 0100", "Jane Doe")

    # The stored CV is untouched
    stored = (await client.get(f"{API}/cvs/{cv_id}")).json()["content"]["personal"]
    assert stored["email"] == "jane@example.com"


def test_contact_details_are_taken_out_of_markdown_cvs():
    markdown = {
        "mode": "markdown",
        "markdown": "# Jane\n\n**jane@example.com** | **+1 555 0100** | 5512 3456\n\n2019 - 2023, 2019-01 - 2023-06",
    }

    hidden = public_content(markdown, show_email=False, show_phone=False)["markdown"]
    assert "jane@example.com" not in hidden and "555 0100" not in hidden and "5512" not in hidden
    assert "# Jane" in hidden and "2019 - 2023, 2019-01 - 2023-06" in hidden

    assert public_content(markdown, show_email=True, show_phone=True) == markdown
    assert public_content("not a cv", True, True) == {}
    assert public_content({"personal": "broken"}, False, False) == {"personal": "broken"}


async def test_switching_off_and_deleting(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id)

    await publish(client, cv_id, is_active=False)
    assert (await client.get(f"{API}/public/cv/jane-doe")).status_code == 404
    assert (await view(client, "jane-doe")).status_code == 404
    # Still the owner's: listed, and the name is kept
    assert [(link["slug"], link["is_active"]) for link in (await client.get(f"{API}/links")).json()] == [
        ("jane-doe", False)
    ]

    assert (await client.delete(f"{API}/cvs/{cv_id}/link")).status_code == 204
    assert (await client.get(f"{API}/links")).json() == []
    assert (await client.delete(f"{API}/cvs/{cv_id}/link")).status_code == 404


async def test_renaming_frees_the_old_name(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id, slug="old-name")

    assert (await publish(client, cv_id, slug="new-name")).status_code == 200

    assert (await client.get(f"{API}/public/cv/old-name")).status_code == 404
    assert (await client.get(f"{API}/public/cv/new-name")).status_code == 200
    assert (await db.execute(select(func.count()).select_from(PublicLink))).scalar_one() == 1


@pytest.mark.parametrize("slug", ["ab", "admin", "juan perez", "-x-", ""])
async def test_bad_names_are_rejected(client, slug):
    cv_id = await make_cv(client)
    assert (await publish(client, cv_id, slug=slug)).status_code == 422


async def test_names_are_unique_across_users(client, db, current_user):
    mine = await make_cv(client)
    await publish(client, mine, slug="shared-name")
    current_user["id"] = "user_other"
    theirs = await make_cv(client)

    taken = await publish(client, theirs, slug="Shared-Name")
    assert taken.status_code == 409

    check = (await client.get(f"{API}/links/check", params={"slug": "shared-name"})).json()
    assert (check["available"], check["reason"]) == (False, "taken")


async def test_name_check(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id, slug="mine")

    async def check(slug, **params):
        return (await client.get(f"{API}/links/check", params={"slug": slug, **params})).json()

    assert (await check("Free-Name")) == {"slug": "free-name", "available": True, "reason": None}
    assert (await check("ab"))["reason"] == "length"
    assert (await check("admin"))["reason"] == "reserved"
    assert (await check("a b"))["reason"] == "format"
    # Taken by another of my CVs, but fine for the CV that holds it
    assert (await check("mine"))["reason"] == "taken"
    assert (await check("mine", cv_id=cv_id))["available"] is True


async def test_links_belong_to_their_owner(client, db, current_user):
    cv_id = await make_cv(client)
    await publish(client, cv_id)
    current_user["id"] = "user_other"

    assert (await client.get(f"{API}/links")).json() == []
    assert (await publish(client, cv_id, slug="hijack")).status_code == 404
    assert (await client.delete(f"{API}/cvs/{cv_id}/link")).status_code == 404
    assert (await client.get(f"{API}/cvs/{cv_id}/link/stats")).status_code == 404
    # Marking "seen" only touches one's own links
    await client.post(f"{API}/links/seen")
    link = (await db.execute(select(PublicLink))).scalar_one()
    assert (link.slug, link.views_seen_at) == ("jane-doe", None)


async def test_deleting_the_cv_or_the_account_removes_the_link(client, db):
    first, second = await make_cv(client, "A"), await make_cv(client, "B")
    await make_pro(db)
    await publish(client, first, slug="first")
    await publish(client, second, slug="second")
    await view(client, "first")

    await client.delete(f"{API}/cvs/{first}")
    assert (await client.get(f"{API}/public/cv/first")).status_code == 404
    assert await views(db) == 0

    await db.delete((await db.execute(select(User).where(User.id == USER))).scalar_one())
    await db.commit()
    assert (await client.get(f"{API}/public/cv/second")).status_code == 404
    assert (await db.execute(select(func.count()).select_from(PublicLink))).scalar_one() == 0


# ── Plans ─────────────────────────────────────────────────────────────────────


async def test_free_plan_has_one_active_link(client, db):
    first, second = await make_cv(client, "A"), await make_cv(client, "B")
    await publish(client, first, slug="first")

    refused = await publish(client, second, slug="second")
    assert refused.status_code == 403
    assert "Upgrade" in refused.json()["detail"]

    # A second one may be prepared switched off, or the first switched off to make room
    assert (await publish(client, second, slug="second", is_active=False)).status_code == 200
    await publish(client, first, slug="first", is_active=False)
    assert (await publish(client, second, slug="second")).status_code == 200
    # Editing the one active link is always allowed
    assert (await publish(client, second, slug="second", show_phone=True)).status_code == 200


async def test_pro_has_no_limit_and_no_badge(client, db):
    await make_cv(client, "warm-up")
    await make_pro(db)
    for index in range(3):
        cv_id = await make_cv(client, f"CV {index}")
        assert (await publish(client, cv_id, slug=f"link-{index}")).status_code == 200

    assert (await client.get(f"{API}/public/cv/link-2")).json()["badge"] is False
    assert [link["paused"] for link in (await client.get(f"{API}/links")).json()] == [False] * 3


async def test_when_pro_ends_only_the_oldest_link_stays_online(client, db):
    await make_cv(client, "warm-up")
    await make_pro(db)
    ids = [await make_cv(client, f"CV {i}") for i in range(3)]
    for index, cv_id in enumerate(ids):
        await publish(client, cv_id, slug=f"link-{index}")

    # The pass ran out and the owner has not been back since
    user = (await db.execute(select(User).where(User.id == USER))).scalar_one()
    user.pro_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    statuses = [(await client.get(f"{API}/public/cv/link-{i}")).status_code for i in range(3)]
    assert statuses == [200, 404, 404]
    assert (await client.get(f"{API}/public/cv/link-0")).json()["badge"] is True
    assert (await view(client, "link-1")).status_code == 404

    listed = (await client.get(f"{API}/links")).json()
    assert [(link["slug"], link["paused"]) for link in listed] == [
        ("link-0", False),
        ("link-1", True),
        ("link-2", True),
    ]
    # Nothing was deleted: upgrading again brings them back
    await make_pro(db)
    assert (await client.get(f"{API}/public/cv/link-2")).status_code == 200


async def test_free_links_can_be_switched_off_altogether(client, db, monkeypatch):
    monkeypatch.setattr(settings, "FREE_PUBLIC_LINK_LIMIT", 0)
    cv_id = await make_cv(client)
    assert (await publish(client, cv_id)).status_code == 403


# ── Views ─────────────────────────────────────────────────────────────────────


async def test_views_are_counted_once_per_visitor_per_half_hour(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id)

    assert (await view(client, "jane-doe", ip="203.0.113.7")).status_code == 204
    await view(client, "jane-doe", ip="203.0.113.7")
    await view(client, "jane-doe", ip="203.0.113.8")
    assert await views(db) == 2

    # The same visitor an hour later is a new view
    for row in (await db.execute(select(LinkView))).scalars():
        row.viewed_at = datetime.now(UTC) - timedelta(minutes=31)
    await db.commit()
    await view(client, "jane-doe", ip="203.0.113.7")
    assert await views(db) == 3


@pytest.mark.parametrize(
    "agent",
    [
        "",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "facebookexternalhit/1.1",
        "WhatsApp/2.23",
        "Slackbot-LinkExpanding 1.0",
        "curl/8.5.0",
        "python-httpx/0.28",
        "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/140.0 Safari/537.36",
    ],
)
async def test_bots_and_previews_are_not_views(client, db, agent):
    cv_id = await make_cv(client)
    await publish(client, cv_id)

    assert (await view(client, "jane-doe", agent=agent)).status_code == 204
    assert await views(db) == 0


async def test_nothing_that_identifies_a_visitor_is_stored(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id)

    await view(client, "jane-doe", ip="203.0.113.99", referrer="https://www.linkedin.com/in/someone?trk=secret#frag")

    row = (await db.execute(select(LinkView))).scalar_one()
    assert row.referrer_host == "linkedin.com"
    assert "203.0.113.99" not in row.visitor and len(row.visitor) == 32
    stored = " ".join(str(getattr(row, column.name)) for column in LinkView.__table__.columns)
    assert "203.0.113" not in stored and "secret" not in stored and "someone" not in stored


def test_visitor_id_cannot_be_followed():
    args = ("203.0.113.7", "Mozilla/5.0", "link-1")
    today, tomorrow = date(2026, 10, 7), date(2026, 10, 8)

    assert visitor_id(*args, day=today) == visitor_id(*args, day=today)
    assert visitor_id(*args, day=today) != visitor_id(*args, day=tomorrow)
    assert visitor_id(*args, day=today) != visitor_id("203.0.113.7", "Mozilla/5.0", "link-2", day=today)
    assert visitor_id(*args, day=today) != visitor_id("203.0.113.8", "Mozilla/5.0", "link-1", day=today)


def test_visitor_id_uses_the_configured_secret(monkeypatch):
    args = ("203.0.113.7", "Mozilla/5.0", "link-1")
    random_key = visitor_id(*args, day=date(2026, 10, 7))
    monkeypatch.setattr(settings, "VIEW_HASH_SECRET", "a-configured-secret")
    assert visitor_id(*args, day=date(2026, 10, 7)) != random_key


@pytest.mark.parametrize(
    ("referrer", "host"),
    [
        ("https://www.linkedin.com/feed/?x=1", "linkedin.com"),
        ("http://t.co/abc", "t.co"),
        ("https://Mail.Google.com/mail/u/0/", "mail.google.com"),
        ("android-app://com.slack/", None),
        ("not a url", None),
        ("https://localhost/x", None),
        ("", None),
        (None, None),
        ("https://[bad", None),
        (f"https://{'a' * 120}.com/", None),
        (42, None),
    ],
)
def test_referrer_host(referrer, host):
    assert referrer_host(referrer) == host


def test_is_bot():
    assert is_bot(None) and is_bot("") and is_bot("Twitterbot/1.0")
    assert not is_bot(BROWSER["User-Agent"])


async def test_view_without_a_body_and_with_junk(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id)

    plain = await client.post(f"{API}/public/cv/jane-doe/view", headers={**BROWSER, "X-Forwarded-For": "198.51.100.1"})
    junk = await client.post(
        f"{API}/public/cv/jane-doe/view",
        json={"referrer": "x" * 3000},
        headers={**BROWSER, "X-Forwarded-For": "198.51.100.2"},
    )

    assert (plain.status_code, junk.status_code) == (204, 422)
    assert await views(db) == 1
    assert (await view(client, "no-such-link")).status_code == 404


# ── Statistics ────────────────────────────────────────────────────────────────


async def seed_views(db, slug="jane-doe"):
    link = (await db.execute(select(PublicLink).where(PublicLink.slug == slug))).scalar_one()
    now = datetime.now(UTC)
    rows = [
        (now - timedelta(hours=1), "v1", "linkedin.com"),
        (now - timedelta(hours=2), "v2", "linkedin.com"),
        (now - timedelta(days=3), "v1", "google.com"),
        (now - timedelta(days=3), "v3", None),
        (now - timedelta(days=40), "v4", "old.example"),
    ]
    db.add_all([LinkView(link_id=link.id, viewed_at=at, visitor=who, referrer_host=host) for at, who, host in rows])
    await db.commit()
    return link


async def test_free_plan_sees_totals_only(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id)
    await seed_views(db)

    stats = (await client.get(f"{API}/cvs/{cv_id}/link/stats")).json()

    assert stats == {"views_total": 5, "visitors_total": 4, "daily": None, "referrers": None}


async def test_pro_sees_days_and_referrers(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id)
    await seed_views(db)
    await make_pro(db)

    stats = (await client.get(f"{API}/cvs/{cv_id}/link/stats")).json()

    assert (stats["views_total"], stats["visitors_total"]) == (5, 4)
    assert len(stats["daily"]) == 30
    assert stats["daily"][-1]["day"] == datetime.now(UTC).date().isoformat()
    # The view from 40 days ago is in the total but outside the chart
    assert sum(day["views"] for day in stats["daily"]) == 4
    three_days_ago = (datetime.now(UTC) - timedelta(days=3)).date().isoformat()
    assert {day["day"]: day["views"] for day in stats["daily"]}[three_days_ago] == 2
    assert stats["referrers"][0] == {"host": "linkedin.com", "views": 2}
    assert {"host": None, "views": 1} in stats["referrers"]
    assert len(stats["referrers"]) == 4


async def test_new_views_until_the_owner_has_looked(client, db):
    cv_id = await make_cv(client)
    await publish(client, cv_id)
    await seed_views(db)

    before = (await client.get(f"{API}/links")).json()[0]
    assert (before["views_total"], before["views_new"]) == (5, 5)

    assert (await client.post(f"{API}/links/seen")).status_code == 204
    seen = (await client.get(f"{API}/links")).json()[0]
    assert (seen["views_total"], seen["views_new"]) == (5, 0)

    await view(client, "jane-doe", ip="198.51.100.50")
    after = (await client.get(f"{API}/links")).json()[0]
    assert (after["views_total"], after["views_new"]) == (6, 1)


async def test_stats_need_a_link(client, db):
    cv_id = await make_cv(client)
    assert (await client.get(f"{API}/cvs/{cv_id}/link/stats")).status_code == 404
    assert (await client.get(f"{API}/cvs/00000000-0000-0000-0000-000000000000/link/stats")).status_code == 404
