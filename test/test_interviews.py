"""Voice mock interview (premium)."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from src.core.config import settings
from src.models.interview import InterviewSession
from src.models.user import User
from src.services.ai import interview as service
from src.services.pro import grant_pro

BASE = "/api/v1/interviews"
USER = "user_test_1"

CV = {
    "personal": {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+1 555 0100",
        "city": "Lisbon",
        "socials": [{"network": "GitHub", "url": "https://github.com/jane"}],
    },
    "experience": [{"company": "Acme", "role": "Lead Developer", "description": ["Led the migration"]}],
}
JOB = "Senior Python engineer for a payments team. Django, PostgreSQL, on-call rotation."


class FakeVoiceAI:
    """Stands in for the OpenAI client: chat, transcription and speech."""

    def __init__(self):
        self.chat_calls, self.heard, self.spoken = [], [], []
        self.follow_up = ""
        self.acknowledgement = "Understood."
        self.plan = None
        self.report = None
        self.transcript = "I led the migration to microservices at Acme."
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(create=self._transcribe),
            speech=SimpleNamespace(create=self._speak),
        )

    async def _chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        system = kwargs["messages"][0]["content"]
        if "preparing a job interview" in system:
            count = int(system.split("Write exactly ")[1].split(" ")[0])
            reply = (
                self.plan
                if self.plan is not None
                else {
                    "title": "Senior Python Engineer",
                    "questions": [
                        {"type": "opening" if i == 0 else "experience", "text": f"Question {i}?"} for i in range(count)
                    ],
                }
            )
        elif "in the middle of a spoken job interview" in system:
            reply = {"acknowledgement": self.acknowledgement, "follow_up": self.follow_up}
        else:
            reply = (
                self.report
                if self.report is not None
                else {
                    "overall_score": 72,
                    "summary": "Solid answers.",
                    "strengths": ["Clear"],
                    "improvements": ["More numbers"],
                    "tips": ["Practise"],
                    "answers": [
                        {"question": i, "score": 7, "went_well": "Good", "improve": "Detail", "sample_answer": "Better"}
                        for i in range(8)
                    ],
                }
            )
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    async def _transcribe(self, **kwargs):
        self.heard.append(kwargs)
        return SimpleNamespace(text=self.transcript)

    async def _speak(self, **kwargs):
        self.spoken.append(kwargs)
        return SimpleNamespace(content=b"ID3-fake-mp3")


@pytest.fixture
def ai(monkeypatch):
    fake = FakeVoiceAI()
    monkeypatch.setattr(service, "get_ai_client", lambda: (fake, "test-model"))
    return fake


async def make_user(db, plan="active", user_id=USER):
    user = User(id=user_id, is_pro=False)
    if plan == "sprint":
        grant_pro(user, 7)
    elif plan == "active":
        grant_pro(user, 30, premium=True)
    elif plan == "lifetime":
        grant_pro(user, None, premium=True)
    db.add(user)
    await db.commit()


async def start(client, **overrides):
    body = {"cv_content": CV, "job_description": JOB, "language": "en", "question_count": 4, **overrides}
    return await client.post(BASE, json=body)


async def say(client, session_id, text="My answer."):
    return await client.post(f"{BASE}/{session_id}/answer", json={"text": text})


async def stored(db):
    return (await db.execute(select(func.count()).select_from(InterviewSession))).scalar_one()


# ── Who may use it ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("plan", ["free", "sprint"])
async def test_only_premium_plans_may_use_interviews(client, db, ai, plan):
    await make_user(db, plan)
    fake_id = "00000000-0000-0000-0000-000000000000"

    for method, path, kwargs in [
        ("post", BASE, {"json": {"cv_content": CV, "job_description": JOB, "language": "en"}}),
        ("get", BASE, {}),
        ("get", f"{BASE}/{fake_id}", {}),
        ("post", f"{BASE}/{fake_id}/answer", {"json": {"text": "hi"}}),
        ("get", f"{BASE}/{fake_id}/turns/0/audio", {}),
        ("post", f"{BASE}/{fake_id}/finish", {}),
        ("delete", f"{BASE}/{fake_id}", {}),
    ]:
        response = await getattr(client, method)(path, **kwargs)
        assert response.status_code == 403, (method, path)
        assert "Active Hunt" in response.json()["detail"]
    assert ai.chat_calls == []


@pytest.mark.parametrize("plan", ["active", "lifetime"])
async def test_premium_plans_can_start(client, db, ai, plan):
    await make_user(db, plan)
    assert (await start(client)).status_code == 201


# ── Starting ──────────────────────────────────────────────────────────────────


async def test_start_prepares_questions_and_greets_by_first_name(client, db, ai):
    await make_user(db)

    response = await start(client, question_count=5)

    assert response.status_code == 201
    session = response.json()
    assert (session["status"], session["question_count"], session["current_question"]) == ("active", 5, 0)
    assert (session["title"], session["done"], session["report"]) == ("Senior Python Engineer", False, None)
    # Only the question being asked is revealed
    assert session["questions"] == ["Question 0?"]
    opening = session["turns"][0]
    assert (opening["role"], opening["kind"], opening["index"]) == ("recruiter", "question", 0)
    assert opening["text"].startswith("Hi Jane, thanks for your time")
    assert opening["text"].endswith("Question 0?")

    # Contact details stay on the server; the posting is data, not part of the instructions
    system, user = ai.chat_calls[0]["messages"]
    sent = json.dumps(ai.chat_calls[0]["messages"])
    for secret in ("jane@example.com", "555 0100", "github.com/jane", "Lisbon"):
        assert secret not in sent
    assert JOB in user["content"] and JOB not in system["content"]
    assert "Acme" in user["content"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"question_count": 3},
        {"question_count": 9},
        {"language": "fr"},
        {"job_description": "too short"},
        {"cv_content": "not an object"},
    ],
)
async def test_invalid_start_requests_cost_nothing(client, db, ai, overrides):
    await make_user(db)
    assert (await start(client, **overrides)).status_code == 422
    assert ai.chat_calls == []
    assert await stored(db) == 0


@pytest.mark.parametrize(
    "plan",
    ["not json", "[]", {"questions": []}, {"questions": [{"text": "Only one?"}]}, {"questions": "nope"}],
)
async def test_unusable_plan_is_a_502_and_not_counted(client, db, ai, plan):
    await make_user(db)
    ai.plan = plan

    response = await start(client)

    assert response.status_code == 502
    assert await stored(db) == 0


async def test_plan_is_trimmed_to_what_was_asked(client, db, ai):
    await make_user(db)
    ai.plan = {
        "title": "T" * 500,
        "is_admin": True,
        "questions": [
            "junk",
            {"type": "nonsense", "text": "Q" * 2000},
            {"type": "technical", "text": ""},
            *[{"type": "behavioral", "text": f"Extra {i}?"} for i in range(20)],
        ],
    }

    session = (await start(client, question_count=4)).json()

    assert (len(session["title"]), session["question_count"]) == (120, 4)
    row = (await db.execute(select(InterviewSession))).scalar_one()
    assert row.questions[0] == {"type": "experience", "text": "Q" * 500}
    assert all(set(q) == {"type", "text"} and q["text"] for q in row.questions)


async def test_daily_and_monthly_caps(client, db, ai, monkeypatch):
    await make_user(db)
    monkeypatch.setattr(settings, "INTERVIEW_DAILY_LIMIT", 2)

    assert (await start(client)).status_code == 201
    assert (await start(client)).status_code == 201
    limited = await start(client)
    assert limited.status_code == 429
    assert "Daily" in limited.json()["detail"]
    assert 0 < int(limited.headers["retry-after"]) <= 24 * 3600

    usage = (await client.get("/api/v1/users/me")).json()["usage"]
    assert (usage["interviews_daily"]["limit"], usage["interviews_daily"]["remaining"]) == (2, 0)
    assert usage["interviews_daily"]["resets_at"] is not None
    assert usage["interviews_monthly"]["remaining"] == 28

    # Yesterday's interviews no longer count for the day, but still for the month
    for row in (await db.execute(select(InterviewSession))).scalars():
        row.created_at = datetime.now(UTC) - timedelta(hours=25)
    await db.commit()
    monkeypatch.setattr(settings, "INTERVIEW_MONTHLY_LIMIT", 3)
    assert (await start(client)).status_code == 201
    monthly = await start(client)
    assert (monthly.status_code, "Monthly" in monthly.json()["detail"]) == (429, True)

    monkeypatch.setattr(settings, "INTERVIEW_DAILY_LIMIT", 0)
    monkeypatch.setattr(settings, "INTERVIEW_MONTHLY_LIMIT", 0)
    assert (await start(client)).status_code == 201


# ── The conversation ──────────────────────────────────────────────────────────


async def test_full_interview_with_typed_answers(client, db, ai):
    await make_user(db)
    session_id = (await start(client, question_count=4)).json()["id"]

    progress = []
    for number in range(4):
        response = await say(client, session_id, f"Answer {number}")
        assert response.status_code == 200
        body = response.json()
        progress.append((body["answer"]["text"], body["reply"]["kind"], body["current_question"], body["done"]))

    assert progress == [
        ("Answer 0", "question", 1, False),
        ("Answer 1", "question", 2, False),
        ("Answer 2", "question", 3, False),
        ("Answer 3", "closing", 4, True),
    ]
    detail = (await client.get(f"{BASE}/{session_id}")).json()
    assert [t["index"] for t in detail["turns"]] == list(range(9))
    assert detail["questions"] == [f"Question {i}?" for i in range(4)]
    assert detail["turns"][2]["text"] == "Understood. Question 1?"
    assert detail["turns"][-1]["text"].startswith("Understood. That is everything from my side")
    assert (detail["done"], detail["status"]) == (True, "active")

    # Nothing more can be said once the recruiter has closed
    assert (await say(client, session_id)).status_code == 409

    finished = await client.post(f"{BASE}/{session_id}/finish")
    assert finished.status_code == 200
    report = finished.json()["report"]
    assert (finished.json()["status"], report["overall_score"]) == ("completed", 72)
    assert [a["question"] for a in report["answers"]] == [0, 1, 2, 3]
    assert finished.json()["completed_at"] is not None

    # Asking again returns the stored report without another model call
    calls = len(ai.chat_calls)
    again = await client.post(f"{BASE}/{session_id}/finish")
    assert again.json()["report"] == report
    assert len(ai.chat_calls) == calls

    history = (await client.get(BASE)).json()
    assert [(h["id"], h["status"], h["overall_score"]) for h in history] == [(session_id, "completed", 72)]


async def test_one_follow_up_per_question_at_most(client, db, ai):
    await make_user(db)
    session_id = (await start(client, question_count=4)).json()["id"]
    ai.follow_up = "Can you give a concrete example?"

    first = (await say(client, session_id, "It went fine.")).json()
    assert (first["reply"]["kind"], first["current_question"]) == ("follow_up", 0)
    assert first["reply"]["text"] == "Understood. Can you give a concrete example?"

    # The model still wants to dig, but the second answer moves the interview on
    second = (await say(client, session_id, "We cut costs by 30%.")).json()
    assert (second["reply"]["kind"], second["current_question"]) == ("question", 1)
    assert "concrete example" not in second["reply"]["text"]
    assert "no time for another follow-up" in ai.chat_calls[-1]["messages"][0]["content"]


async def test_spoken_answer_is_transcribed(client, db, ai):
    await make_user(db)
    session_id = (await start(client, language="es")).json()["id"]

    response = await client.post(
        f"{BASE}/{session_id}/answer",
        content=b"\x1aE\xdf\xa3 fake webm bytes",
        headers={"Content-Type": "audio/webm;codecs=opus"},
    )

    assert response.status_code == 200
    assert response.json()["answer"]["text"] == "I led the migration to microservices at Acme."
    sent = ai.heard[0]
    assert (sent["model"], sent["language"]) == (settings.OPENAI_STT_MODEL, "es")
    assert sent["file"][0] == "answer.webm" and sent["file"][2] == "audio/webm"
    # The answer is data for the recruiter model, never part of its instructions
    system, user = ai.chat_calls[-1]["messages"]
    assert "I led the migration" in user["content"] and "I led the migration" not in system["content"]
    assert "Spanish" in system["content"]


async def test_bad_recordings_are_rejected(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    url = f"{BASE}/{session_id}/answer"

    empty = await client.post(url, content=b"", headers={"Content-Type": "audio/webm"})
    wrong_type = await client.post(url, content=b"x", headers={"Content-Type": "video/mp4"})
    too_big = await client.post(url, content=b"x" * (5 * 1024 * 1024 + 1), headers={"Content-Type": "audio/mp4"})
    ai.transcript = "   "
    silence = await client.post(url, content=b"x", headers={"Content-Type": "audio/ogg"})
    blank = await client.post(url, json={"text": "   "})
    not_json = await client.post(url, content=b"{", headers={"Content-Type": "application/json"})

    assert [r.status_code for r in (empty, wrong_type, too_big, silence, blank, not_json)] == [
        422,
        415,
        413,
        422,
        422,
        422,
    ]
    assert "could not hear" in silence.json()["detail"]
    # None of it became part of the interview
    assert len((await client.get(f"{BASE}/{session_id}")).json()["turns"]) == 1


async def test_long_transcripts_are_cut(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    ai.transcript = "word " * 5000

    response = await client.post(f"{BASE}/{session_id}/answer", content=b"x", headers={"Content-Type": "audio/wav"})

    assert len(response.json()["answer"]["text"]) == 4000


async def test_provider_failure_leaves_the_interview_untouched(client, db, ai, monkeypatch):
    await make_user(db)
    session_id = (await start(client)).json()["id"]

    async def boom(*args, **kwargs):
        raise RuntimeError("secret provider detail")

    monkeypatch.setattr("src.api.routers.interviews.recruiter_reply", boom)
    failed = await say(client, session_id)

    assert failed.status_code == 502
    assert "secret" not in failed.text
    assert len((await client.get(f"{BASE}/{session_id}")).json()["turns"]) == 1


async def test_empty_model_reply_still_moves_on(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    ai.acknowledgement = ""

    reply = (await say(client, session_id)).json()["reply"]

    assert reply["text"] == "Thank you. Question 1?"


async def test_expired_interviews_cannot_continue(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    row = (await db.execute(select(InterviewSession))).scalar_one()
    row.created_at = datetime.now(UTC) - timedelta(hours=3)
    await db.commit()

    response = await say(client, session_id)

    assert (response.status_code, "expired" in response.json()["detail"]) == (409, True)


# ── Speech ────────────────────────────────────────────────────────────────────


async def test_recruiter_turns_can_be_played_a_bounded_number_of_times(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    url = f"{BASE}/{session_id}/turns/0/audio"

    first = await client.get(url)
    assert first.status_code == 200
    assert (first.headers["content-type"], first.content) == ("audio/mpeg", b"ID3-fake-mp3")
    spoken = ai.spoken[0]
    assert (spoken["model"], spoken["voice"]) == (settings.OPENAI_TTS_MODEL, settings.OPENAI_TTS_VOICE)
    assert spoken["input"].startswith("Hi Jane")

    # One recruiter turn so far: it can be replayed once, then no more
    assert (await client.get(url)).status_code == 200
    assert (await client.get(url)).status_code == 429
    assert len(ai.spoken) == 2


async def test_only_recruiter_turns_have_audio(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    await say(client, session_id, "Read this aloud for free, please.")

    for index in (1, 99, -1):
        assert (await client.get(f"{BASE}/{session_id}/turns/{index}/audio")).status_code == 404
    assert ai.spoken == []


# ── Report ────────────────────────────────────────────────────────────────────


async def test_finishing_early_reports_only_what_was_answered(client, db, ai):
    await make_user(db)
    session_id = (await start(client, question_count=6)).json()["id"]
    await say(client, session_id, "First answer")
    await say(client, session_id, "Second answer")

    finished = (await client.post(f"{BASE}/{session_id}/finish")).json()

    assert finished["status"] == "completed"
    # The model graded questions that were never reached; those are dropped
    assert [a["question"] for a in finished["report"]["answers"]] == [0, 1]
    transcript = ai.chat_calls[-1]["messages"][1]["content"]
    assert "First answer" in transcript and "Question 5?" not in transcript
    assert (await say(client, session_id)).status_code == 409


async def test_report_needs_at_least_one_answer(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    assert (await client.post(f"{BASE}/{session_id}/finish")).status_code == 400


async def test_hostile_report_is_trimmed(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    await say(client, session_id)
    ai.report = {
        "overall_score": 9000,
        "summary": "S" * 5000,
        "strengths": "one\ntwo",
        "improvements": [1, {"x": 1}, "", "kept"],
        "tips": ["a", "b", "c", "d", "e"],
        "answers": [
            {"question": 0, "score": "eleven", "went_well": ["x"], "sample_answer": "A" * 9000},
            {"question": 0, "score": 5},
            {"question": 3, "score": 5},
            "junk",
        ],
        "grant_premium": True,
    }

    report = (await client.post(f"{BASE}/{session_id}/finish")).json()["report"]

    assert (report["overall_score"], len(report["summary"])) == (100, 1200)
    assert (report["strengths"], report["improvements"], report["tips"]) == (
        ["one", "two"],
        ["1", "kept"],
        ["a", "b", "c"],
    )
    assert len(report["answers"]) == 1
    first = report["answers"][0]
    assert (first["score"], first["went_well"], len(first["sample_answer"])) == (0, "", 1500)
    assert "grant_premium" not in report


@pytest.mark.parametrize("report", ["not json", "[]", {}])
async def test_unusable_report_is_a_502_and_can_be_retried(client, db, ai, report):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    await say(client, session_id)
    ai.report = report

    assert (await client.post(f"{BASE}/{session_id}/finish")).status_code == 502
    assert (await client.get(f"{BASE}/{session_id}")).json()["status"] == "active"

    ai.report = None
    assert (await client.post(f"{BASE}/{session_id}/finish")).json()["status"] == "completed"


# ── Privacy between users, and clean-up ───────────────────────────────────────


async def test_sessions_belong_to_their_owner(client, db, ai, current_user):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    await make_user(db, user_id="user_other")
    current_user["id"] = "user_other"

    assert (await client.get(BASE)).json() == []
    for method, path, kwargs in [
        ("get", f"{BASE}/{session_id}", {}),
        ("post", f"{BASE}/{session_id}/answer", {"json": {"text": "hi"}}),
        ("get", f"{BASE}/{session_id}/turns/0/audio", {}),
        ("post", f"{BASE}/{session_id}/finish", {}),
        ("delete", f"{BASE}/{session_id}", {}),
    ]:
        assert (await getattr(client, method)(path, **kwargs)).status_code == 404, (method, path)
    assert await stored(db) == 1


async def test_delete_and_account_removal(client, db, ai):
    await make_user(db)
    first = (await start(client)).json()["id"]
    await start(client)

    assert (await client.delete(f"{BASE}/{first}")).status_code == 204
    assert (await client.get(f"{BASE}/{first}")).status_code == 404
    assert await stored(db) == 1

    # Deleting the user removes their interviews with them
    await db.delete((await db.execute(select(User).where(User.id == USER))).scalar_one())
    await db.commit()
    assert await stored(db) == 0


async def test_losing_premium_locks_history_too(client, db, ai):
    await make_user(db)
    session_id = (await start(client)).json()["id"]
    user = (await db.execute(select(User).where(User.id == USER))).scalar_one()
    user.premium_until = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    assert (await client.get(f"{BASE}/{session_id}")).status_code == 403
    assert (await client.get("/api/v1/users/me")).json()["plan"] == "sprint"


def test_greeting_handles_missing_names():
    assert service.greeting("es", {}).startswith("Hola, gracias")
    assert service.greeting("pt", {"personal": {"name": "  "}}).startswith("Olá, obrigado")
    assert service.greeting("en", {"personal": {"name": "María José Pérez"}}).startswith("Hi María,")
    assert service.greeting("en", {"personal": "broken"}).startswith("Hi, thanks")
