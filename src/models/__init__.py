# Import every model so it is registered on Base.metadata (Alembic autogenerate, tests)
from src.models import ai_request, cv, interview, payment, promo, public_link, user  # noqa: F401
