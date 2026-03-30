import pytest
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise
from main import app

# 1. 
# initialize the database for the test environment
@pytest.fixture(autouse=True)
async def setup_database():
    # start Tortoise
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["deps.database"]}
    )
    # create the 'users' table
    await Tortoise.generate_schemas()
    
    yield  # The individual test runs here
    
    # close connections so the next test gets a fresh database
    await Tortoise.close_connections()


# 2. setup the async test client
@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# 3. actual tests
async def test_signup_success(client):
    response = await client.post(
        "/auth/signup",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "supersecret123"
        }
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"


async def test_signup_duplicate_username(client):
    #sign up the user
    await client.post(
        "/auth/signup",
        json={"username": "testuser", "email": "test@example.com", "password": "supersecret123"}
    )
    # tries to sign them up again with a new email, but the same username
    response = await client.post(
        "/auth/signup",
        json={"username": "testuser", "email": "different@example.com", "password": "supersecret123"}
    )
    assert response.status_code == 400


async def test_login_success(client):
    # create the user first
    await client.post(
        "/auth/signup",
        json={"username": "testuser", "email": "test@example.com", "password": "supersecret123"}
    )
    # now log them in
    response = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "supersecret123"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

#️ tests for the wrong password
async def test_login_wrong_password(client):
    await client.post(
        "/auth/signup",
        json={"username": "testuser", "email": "test@example.com", "password": "supersecret123"}
    )
    response = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "wrongpassword!"}
    )
    assert response.status_code == 401

#️ tests GET function for current user
async def test_get_current_user(client):
    await client.post(
        "/auth/signup",
        json={"username": "testuser", "email": "test@example.com", "password": "supersecret123"}
    )
    login_resp = await client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "supersecret123"}
    )
    
    token = login_resp.json()["access_token"]

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"

#️ tests for no token
async def test_get_current_user_no_token(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401