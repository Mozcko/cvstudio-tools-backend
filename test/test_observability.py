import sys
from types import SimpleNamespace

from src.core import observability
from src.core.config import settings
from src.core.observability import init_error_reporting, scrub_event


def make_event():
    return {
        "request": {
            "url": "https://api.example/api/v1/ai/rewrite",
            "method": "POST",
            "data": {"cv_content": {"personal": {"email": "jane@example.com"}}, "job_description": "secret jd"},
            "cookies": {"__session": "abc"},
            "query_string": "id=1",
            "headers": {
                "Authorization": "Bearer token",
                "Cookie": "__session=abc",
                "Stripe-Signature": "t=1,v1=x",
                "svix-signature": "v1,x",
                "User-Agent": "pytest",
                "Content-Type": "application/json",
            },
        },
        "user": {"id": "user_1", "email": "jane@example.com", "ip_address": "1.2.3.4"},
        "exception": {"values": [{"type": "RuntimeError", "value": "boom"}]},
    }


def test_scrub_removes_bodies_credentials_and_personal_data():
    event = scrub_event(make_event())

    request = event["request"]
    assert "data" not in request and "cookies" not in request and "query_string" not in request
    assert request["headers"] == {"User-Agent": "pytest", "Content-Type": "application/json"}
    assert event["user"] == {"id": "user_1"}
    # The error itself is what we want to keep
    assert event["exception"]["values"][0]["value"] == "boom"

    flat = str(event)
    for leaked in ("jane@example.com", "secret jd", "Bearer token", "1.2.3.4", "__session"):
        assert leaked not in flat


def test_scrub_tolerates_events_without_a_request():
    assert scrub_event({"message": "hello"}) == {"message": "hello"}
    assert scrub_event({"request": None, "user": {"email": "a@b.c"}}) == {"request": None, "user": {}}
    assert scrub_event({"request": {"headers": [["a", "b"]]}}) == {"request": {"headers": [["a", "b"]]}}


def test_reporting_is_off_without_a_dsn(monkeypatch):
    monkeypatch.setattr(settings, "SENTRY_DSN", None)
    assert init_error_reporting() is False


def test_reporting_starts_with_privacy_safe_options(monkeypatch):
    captured = {}
    fake_sdk = SimpleNamespace(init=lambda **kwargs: captured.update(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://public@example.ingest.sentry.io/1")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")

    assert init_error_reporting() is True

    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["traces_sample_rate"] == 0.0
    assert captured["before_send"] is observability.scrub_event
    assert captured["release"] == "abc123"
    assert captured["environment"] == settings.ENVIRONMENT
