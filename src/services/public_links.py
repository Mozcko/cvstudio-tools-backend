"""Public CV links: names, who may be served, what is shown, and anonymous view counting."""

import copy
import hashlib
import hmac
import re
import secrets
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.public_link import PublicLink
from src.models.user import User
from src.utils.sanitizer import EMAIL_RE, _looks_like_dates

# ── Addresses ─────────────────────────────────────────────────────────────────
#
# A link lives at /u/<key>/<name>. The key identifies it; the name is there to be read and can
# be anything the owner likes, including a name someone else uses.

SLUG_MIN, SLUG_MAX = 3, 40
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

KEY_LENGTH = 8
KEY_RE = re.compile(r"^[a-z0-9]{8}$")
# No 0/o, 1/l/i: keys get read aloud and typed by hand
KEY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def normalize_slug(value: str) -> str:
    return value.strip().lower()


def slug_problem(slug: str) -> str | None:
    """Why a (normalized) name cannot be used, or None when it is fine."""
    if not SLUG_MIN <= len(slug) <= SLUG_MAX:
        return "length"
    if not SLUG_RE.match(slug) or "--" in slug:
        return "format"
    return None


def new_key() -> str:
    """A random key. 31^8 possibilities: not guessable, and collisions are retried by the caller."""
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))


def key_from_ref(ref: str) -> str | None:
    """
    The key in what the site asks for: normally the key itself, "k7f2m9qx". The older form
    "juan-perez-k7f2m9qx" is still understood. The name is never used for lookup, so a link
    keeps working after its owner renames it.
    """
    candidate = ref.strip().lower().rsplit("-", 1)[-1]
    return candidate if KEY_RE.match(candidate) else None


# ── Lookup ────────────────────────────────────────────────────────────────────


async def find_public_link(db: AsyncSession, *, key: str) -> PublicLink | None:
    """The link a public request refers to, whatever its state."""
    result = await db.execute(select(PublicLink).where(PublicLink.key == key))
    return result.scalar_one_or_none()


async def served_link_ids(db: AsyncSession, user: User) -> set:
    """
    The user's links that are actually online. Pro: every active link. Otherwise only the
    oldest FREE_PUBLIC_LINK_LIMIT active ones; the rest are paused, not deleted, so they come
    back if the user upgrades again.
    """
    result = await db.execute(
        select(PublicLink.id)
        .where(PublicLink.user_id == user.id, PublicLink.is_active.is_(True))
        .order_by(PublicLink.created_at, PublicLink.id)
    )
    ids = [row[0] for row in result]
    return set(ids if user.is_pro else ids[: max(0, settings.FREE_PUBLIC_LINK_LIMIT)])


# ── What the public sees ──────────────────────────────────────────────────────


# Anything shaped like a phone number, short local ones included. Deliberately broader than the
# pattern used for AI masking: here a miss publishes someone's number
PHONE_IN_TEXT_RE = re.compile(r"(?<![\w/])\+?\(?\d(?:[ .\-]?[()]?[ ]?\d){6,14}(?![\w/])")


def public_content(content: Any, show_email: bool, show_phone: bool) -> Any:
    """A copy of the CV content with the contact details the owner chose to keep private removed."""
    if not isinstance(content, dict):
        return {}
    shown = copy.deepcopy(content)

    if shown.get("mode") == "markdown" and isinstance(shown.get("markdown"), str):
        # Hand-written Markdown has no fields: take the patterns out of the text
        text = shown["markdown"]
        if not show_email:
            text = EMAIL_RE.sub("", text)
        if not show_phone:
            text = PHONE_IN_TEXT_RE.sub(lambda m: m.group(0) if _looks_like_dates(m.group(0)) else "", text)
        shown["markdown"] = text
        return shown

    personal = shown.get("personal")
    if isinstance(personal, dict):
        if not show_email:
            personal["email"] = ""
        if not show_phone:
            personal["phone"] = ""
    return shown


# ── View counting ─────────────────────────────────────────────────────────────

# Not people: crawlers, link previews in chat apps, monitoring and scripts
BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|discord|slack|embedly|"
    r"headless|lighthouse|pingdom|uptime|monitor|curl|wget|python|httpx|okhttp|axios|go-http|java/",
    re.IGNORECASE,
)

_process_secret = secrets.token_bytes(32)


def is_bot(user_agent: str | None) -> bool:
    return not user_agent or bool(BOT_RE.search(user_agent))


def visitor_id(ip: str, user_agent: str, link_id: Any, day: date | None = None) -> str:
    """
    An identifier that is the same for one visitor on one link during one day, and cannot be
    turned back into an IP address or followed to the next day or to another link.
    """
    day = day or datetime.now(UTC).date()
    secret = settings.VIEW_HASH_SECRET.encode() if settings.VIEW_HASH_SECRET else _process_secret
    daily_key = hmac.new(secret, day.isoformat().encode(), hashlib.sha256).digest()
    message = f"{link_id}|{ip}|{user_agent}".encode()
    return hmac.new(daily_key, message, hashlib.sha256).hexdigest()[:32]


def referrer_host(referrer: str | None) -> str | None:
    """Only the host of where the visitor came from ("www." dropped), never the full address."""
    if not referrer or not isinstance(referrer, str):
        return None
    try:
        parts = urlsplit(referrer.strip()[:2000])
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = parts.hostname
    if not host or "." not in host or len(host) > 100:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host
