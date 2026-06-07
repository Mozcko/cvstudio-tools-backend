# CV Studio Tools Backend

A robust FastAPI-based backend service for CV/Resume optimization tools. This service provides AI-powered features including CV improvements, cover letter generation, ATS (Applicant Tracking System) analysis, and professional translation.

## 🚀 Features

- **AI-Powered CV Optimization:** Enhanced by DeepSeek and OpenAI models.
- **Cover Letter Generation:** Tailored cover letters based on user CVs and job descriptions.
- **ATS Analysis:** Intelligent analysis to help resumes pass through automated filters.
- **CV Translation:** Professional translation services for international job markets.
- **Secure Authentication:** Integrated with Clerk for seamless user management.
- **Subscription Management:** Stripe integration for handling Pro memberships.
- **Asynchronous Database Ops:** High-performance database interactions using SQLAlchemy and PostgreSQL.

## 🛠 Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **Database:** PostgreSQL with [SQLAlchemy](https://www.sqlalchemy.org/) (Async)
- **Authentication:** [Clerk](https://clerk.com/)
- **Payments:** [Stripe](https://stripe.com/)
- **AI Models:** DeepSeek & OpenAI
- **Migrations:** [Alembic](https://alembic.sqlalchemy.org/)
- **Containerization:** Docker & Docker Compose

## 📁 Project Structure

```text
├── src/
│   ├── api/            # API routers and dependencies
│   ├── core/           # Configuration and security
│   ├── db/             # Database connection and session management
│   ├── models/         # SQLAlchemy database models
│   ├── schemas/        # Pydantic models for validation
│   ├── services/       # Business logic (AI, Stripe, etc.)
│   └── scripts/        # Utility scripts
├── migrations/         # Alembic database migrations
├── test/               # Pytest suite
└── docker-compose.yml  # Docker orchestration
```

## 🚦 Getting Started

### Prerequisites

- Python 3.10+
- Docker & Docker Compose (optional, for containerized setup)
- PostgreSQL (if running locally)

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd cvstudio-tools-backend
   ```

2. **Set up a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configuration:**
   Copy the example environment file and fill in your credentials:
   ```bash
   cp .env.example .env
   ```

### Running the Application

#### Using Docker (Recommended)
```bash
docker-compose up --build
```

#### Local Development
```bash
uvicorn src.main:app --reload
```
The API will be available at `http://localhost:8000`. Swagger documentation can be found at `http://localhost:8000/docs`.

### Database Migrations

Apply migrations to your database:
```bash
alembic upgrade head
```

To create a new migration after model changes:
```bash
alembic revision --autogenerate -m "description of changes"
```

## 🧪 Testing

Run the test suite using `pytest`:
```bash
pytest
```

## 🔑 Authentication & API Versioning

- **API Versioning:** All endpoints are prefixed with `/api/v1`.
- **Auth:** Protected routes require a valid Clerk token. Use the `get_current_user` dependency in your routers.

## 🛠 Utilities

### Manual User Upgrade
To manually grant Pro status to a user:
```bash
python src/scripts/upgrade_user.py --user-id "user_..."
# OR
python src/scripts/upgrade_user.py --email "user@example.com"
```

## 📄 License

[Specify License, e.g., MIT]
