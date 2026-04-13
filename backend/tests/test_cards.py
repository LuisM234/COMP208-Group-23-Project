import pytest
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise
from main import app

#fixtures
@pytest.fixture(autouse=True)
async def setup_database():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["deps.database"]},
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


#helper - register + login, return auth headers and user data
async def create_user_and_login(client, username="alice", email="alice@example.com", password="secret123"):
    await client.post(
        "/auth/signup",
        json={"username": username, "email": email, "password": password},
    )
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


#helper - creates a deck and return its id
async def create_deck(client, headers, title="My Deck"):
    resp = await client.post("/decks/", json={"title": title, "description": ""}, headers=headers)
    return resp.json()["id"]



# POST
async def test_create_card_success(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "What is 2+2?", "answer": "4"},
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["question"] == "What is 2+2?"
    assert data["answer"] == "4"
    assert data["deck_id"] == deck_id
    assert data["is_ai_generated"] is False


async def test_create_card_wrong_deck(client):
    """Creating a card in a deck that doesn't belong to the user returns 404."""
    headers = await create_user_and_login(client)

    # Create the deck as a different user
    headers2 = await create_user_and_login(client, username="bob", email="bob@example.com")
    deck_id = await create_deck(client, headers2, title="Bob's Deck")

    resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "Q?", "answer": "A"},
        headers=headers,  # alice tries to add card to bob's deck
    )
    assert resp.status_code == 404


async def test_create_card_no_auth(client):
    """Creating a card without a token returns 401."""
    resp = await client.post(
        "/decks/1/cards",
        json={"question": "Q?", "answer": "A"},
    )
    assert resp.status_code == 401


#GET cards in decks
async def test_list_cards_empty(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    resp = await client.get(f"/decks/{deck_id}/cards", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_cards_returns_only_own_deck_cards(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    #add two cards
    await client.post(f"/decks/{deck_id}/cards", json={"question": "Q1", "answer": "A1"}, headers=headers)
    await client.post(f"/decks/{deck_id}/cards", json={"question": "Q2", "answer": "A2"}, headers=headers)

    resp = await client.get(f"/decks/{deck_id}/cards", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_list_cards_wrong_deck(client):
    """Listing cards for another user's deck returns 404."""
    headers = await create_user_and_login(client)
    headers2 = await create_user_and_login(client, username="bob", email="bob@example.com")
    deck_id = await create_deck(client, headers2)

    resp = await client.get(f"/decks/{deck_id}/cards", headers=headers)
    assert resp.status_code == 404



#GET single card
async def test_get_card_success(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    create_resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "Capital of France?", "answer": "Paris"},
        headers=headers,
    )
    card_id = create_resp.json()["id"]

    resp = await client.get(f"/cards/{card_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Paris"


async def test_get_card_not_found(client):
    headers = await create_user_and_login(client)

    resp = await client.get("/cards/9999", headers=headers)
    assert resp.status_code == 404


async def test_get_card_other_users_card(client):
    """Fetching another user's card returns 404, not 403."""
    headers = await create_user_and_login(client)
    headers2 = await create_user_and_login(client, username="bob", email="bob@example.com")

    deck_id = await create_deck(client, headers2)
    create_resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "Q?", "answer": "A"},
        headers=headers2,
    )
    card_id = create_resp.json()["id"]

    #security check
    resp = await client.get(f"/cards/{card_id}", headers=headers)
    assert resp.status_code == 404



#PUT 
async def test_update_card_question(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    create_resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "Old Q", "answer": "Old A"},
        headers=headers,
    )
    card_id = create_resp.json()["id"]

    resp = await client.put(f"/cards/{card_id}", json={"question": "New Q"}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["question"] == "New Q"
    assert data["answer"] == "Old A"  #answer unchanged


async def test_update_card_both_fields(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    create_resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "Old Q", "answer": "Old A"},
        headers=headers,
    )
    card_id = create_resp.json()["id"]

    resp = await client.put(
        f"/cards/{card_id}",
        json={"question": "New Q", "answer": "New A"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["question"] == "New Q"
    assert data["answer"] == "New A"


async def test_update_card_not_found(client):
    headers = await create_user_and_login(client)

    resp = await client.put("/cards/9999", json={"question": "X"}, headers=headers)
    assert resp.status_code == 404


#DELETE cards
async def test_delete_card_success(client):
    headers = await create_user_and_login(client)
    deck_id = await create_deck(client, headers)

    create_resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "Q?", "answer": "A"},
        headers=headers,
    )
    card_id = create_resp.json()["id"]

    resp = await client.delete(f"/cards/{card_id}", headers=headers)
    assert resp.status_code == 204

    #card should now be gone
    get_resp = await client.get(f"/cards/{card_id}", headers=headers)
    assert get_resp.status_code == 404


async def test_delete_card_not_found(client):
    headers = await create_user_and_login(client)

    resp = await client.delete("/cards/9999", headers=headers)
    assert resp.status_code == 404


async def test_delete_card_other_user(client):
    """Deleting another user's card returns 404."""
    headers = await create_user_and_login(client)
    headers2 = await create_user_and_login(client, username="bob", email="bob@example.com")

    deck_id = await create_deck(client, headers2)
    create_resp = await client.post(
        f"/decks/{deck_id}/cards",
        json={"question": "Q?", "answer": "A"},
        headers=headers2,
    )
    card_id = create_resp.json()["id"]

    #making sure other users cant delete other users cards
    resp = await client.delete(f"/cards/{card_id}", headers=headers)
    assert resp.status_code == 404
