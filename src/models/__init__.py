# Import every model so it is registered on Base.metadata (Alembic autogenerate, tests)
from src.models import ai_request, cv, payment, promo, user  # noqa: F401
