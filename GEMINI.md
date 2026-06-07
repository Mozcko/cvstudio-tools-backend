# CV Studio Tools Backend

A FastAPI-based backend service for CV/Resume optimization tools, featuring AI-powered improvements, cover letter generation, ATS analysis, and translation.

## Project Overview

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **Database:** PostgreSQL with [SQLAlchemy](https://www.sqlalchemy.org/) (Async)
- **Authentication:** [Clerk](https://clerk.com/) (external provider, user IDs synchronized to local DB)
- **Payments:** [Stripe](https://stripe.com/)
- **AI Integration:** [DeepSeek](https://www.deepseek.com/) and [OpenAI](https://openai.com/)
- **Migrations:** [Alembic](https://alembic.sqlalchemy.org/)
- **Containerization:** Docker & Docker Compose

## Architecture

- `src/api/routers`: API endpoints categorized by feature (AI, CV, Billing, etc.)
- `src/models`: SQLAlchemy database models.
- `src/schemas`: Pydantic models for request/response validation.
- `src/services`: Business logic, including Stripe integration and AI providers.
- `src/core`: Configuration and security logic.
- `src/db`: Database connection and session management.

## Building and Running

### Using Docker (Recommended)
```bash
docker-compose up --build
```

### Local Development
1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Configure environment variables in a `.env` file (refer to `.env.example`).
3. Run the application:
   ```bash
   uvicorn src.main:app --reload
   ```

### Database Migrations
- Create a new migration:
  ```bash
  alembic revision --autogenerate -m "message"
  ```
- Apply migrations:
  ```bash
  alembic upgrade head
  ```

## Testing

Run tests using `pytest`:
```bash
pytest
```
Tests are located in the `test/` directory. We use `httpx` for async API testing and `unittest.mock` for mocking dependencies.

## Development Conventions

- **Async First:** Use `async/await` for all I/O operations (database, external APIs).
- **Dependency Injection:** Utilize FastAPI's `Depends` for database sessions and authentication.
- **Type Safety:** Heavily use Pydantic schemas and Python type hints.
- **API Versioning:** All endpoints are prefixed with `/api/v1`.
- **Environment Management:** Configuration is managed via Pydantic Settings in `src/core/config.py`.
- **Authentication:** Use `get_current_user` dependency from `src/api/dependencies.py` to ensure user existence and subscription status.

## Utilities

### Manual User Upgrade
To manually grant Pro status to a user (e.g., for testing or manual sales):
```bash
python src/scripts/upgrade_user.py --user-id "user_..."
# OR
python src/scripts/upgrade_user.py --email "user@example.com"
```
