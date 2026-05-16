import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from deps.database import Card, Deck, MCQQuestion
from deps.gemini import GeminiResponse, GeneratedMCQ, get_gemini_wrapper
from main import app


@pytest.fixture(autouse=True)
async def setup_database():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["deps.database"]},
    )
    await Tortoise.generate_schemas()

    yield

    app.dependency_overrides.clear()
    await Tortoise.close_connections()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


async def create_user_and_login(
    client,
    username="aiuser",
    email="ai@example.com",
    password="secret123",
):
    await client.post(
        "/auth/signup",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )

    response = await client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def create_deck(client, headers, title="AI Test Deck"):
    response = await client.post(
        "/decks/",
        json={
            "title": title,
            "description": "Deck used for AI tests",
        },
        headers=headers,
    )
    return response.json()["id"]


class FakeGeminiSuccess:
    async def generate_mcq_questions(self, notes, num_questions, difficulty):
        questions = [
            GeneratedMCQ(
                question="What is photosynthesis?",
                option_a="A process used by plants to make food",
                option_b="A type of rock",
                option_c="A programming language",
                option_d="A planet",
                correct_answer="A",
                explanation="Plants use light energy to make glucose.",
            )
        ]

        response = GeminiResponse(
            model_name="fake-gemini",
            status="success",
            error_code=None,
            error_message=None,
            raw_response="successful response",
        )

        return questions, response


class FakeGeminiFailure:
    async def generate_mcq_questions(self, notes, num_questions, difficulty):
        response = GeminiResponse(
            model_name="fake-gemini",
            status="failed",
            error_code=500,
            error_message=" Gemini failure",
            raw_response="failed response",
        )

        return None, response


async def test_generate_mcq_success_from_notes(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    app.dependency_overrides[get_gemini_wrapper] = lambda: FakeGeminiSuccess()

    response = await client.post(
        "/ai/generate-mcq",
        json={
            "deck_id": deck_id,
            "notes": "Photosynthesis is how plants make food using sunlight.",
            "num_questions": 1,
            "difficulty": "easy",
        },
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()
    assert len(data) == 1
    assert data[0]["question"] == "What is photosynthesis?"
    assert data[0]["correct_answer"] == "A"
    assert data[0]["difficulty"] == "easy"

    saved_questions = await MCQQuestion.all()
    assert len(saved_questions) == 1
    assert saved_questions[0].question == "What is photosynthesis?"


async def test_generate_mcq_uses_deck_cards_when_notes_missing(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    await Card.create(
        deck_id=deck_id,
        question="What is gravity?",
        answer="A force that attracts objects with mass.",
        is_ai_generated=False,
    )

    app.dependency_overrides[get_gemini_wrapper] = lambda: FakeGeminiSuccess()

    response = await client.post(
        "/ai/generate-mcq",
        json={
            "deck_id": deck_id,
            "num_questions": 1,
            "difficulty": "medium",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_generate_mcq_empty_deck_without_notes_returns_400(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    app.dependency_overrides[get_gemini_wrapper] = lambda: FakeGeminiSuccess()

    response = await client.post(
        "/ai/generate-mcq",
        json={
            "deck_id": deck_id,
            "num_questions": 1,
            "difficulty": "medium",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Deck has no cards to use as source material"


async def test_generate_mcq_wrong_deck_returns_404(client):
    headers = await create_user_and_login(client)
    other_headers = await create_user_and_login(
        client,
        username="otheruser",
        email="other@example.com",
    )
    other_deck_id = await create_deck(client, other_headers)

    app.dependency_overrides[get_gemini_wrapper] = lambda: FakeGeminiSuccess()

    response = await client.post(
        "/ai/generate-mcq",
        json={
            "deck_id": other_deck_id,
            "notes": "Some notes",
            "num_questions": 1,
            "difficulty": "hard",
        },
        headers=headers,
    )

    assert response.status_code == 404


async def test_generate_mcq_gemini_failure_returns_502(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    app.dependency_overrides[get_gemini_wrapper] = lambda: FakeGeminiFailure()

    response = await client.post(
        "/ai/generate-mcq",
        json={
            "deck_id": deck_id,
            "notes": "Some notes",
            "num_questions": 1,
            "difficulty": "medium",
        },
        headers=headers,
    )

    assert response.status_code == 502
    assert "Gemini API error" in response.json()["detail"]


async def test_generate_mcq_without_login_returns_401(client):
    response = await client.post(
        "/ai/generate-mcq",
        json={
            "deck_id": 1,
            "notes": "Some notes",
            "num_questions": 1,
            "difficulty": "medium",
        },
    )

    assert response.status_code == 401


async def test_generate_cards_wrong_deck_returns_404(client):
    headers = await create_user_and_login(client)

    response = await client.post(
        "/ai/generate-cards",
        json={
            "deck_id": 9999,
            "notes": "Some notes",
            "num_cards": 2,
        },
        headers=headers,
    )

    assert response.status_code == 404

