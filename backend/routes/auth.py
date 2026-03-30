#️ auth.py includes:
#️ 1. POST /signup  — create a new user
#️ 2. POST /login   — authenticate and return JWT token
#️ 3. GET  /me      — return current user info

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from deps.security import hash_password, verify_password, create_access_token, get_current_user
from deps.database import User

router = APIRouter()


#️
#️ Request/Response Schemas
#️

class SignupRequest(BaseModel):
    #️ what the frontend sends when signing up
    username: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    #️ what the frontend sends when logging in
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    #️ what the backend sends back after login
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    #️ what the backend sends back for /me
    #️ NOTE: no password_hash here — never expose that
    id: int
    username: str
    email: str


#️
#️ 1. Signup Endpoint
#️

@router.post("/signup", response_model=UserResponse)
async def signup(data: SignupRequest):
    #️ check if email already exists
    existing_email = await User.get_or_none(email=data.email)
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    #️ check if username already exists
    existing_username = await User.get_or_none(username=data.username)
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    #️ hash the password
    hashed = hash_password(data.password)

    #️ create the user in database
    user = await User.create(
        username=data.username,
        email=data.email,
        password_hash=hashed
    )

    return UserResponse(id=user.id, username=user.username, email=user.email)


#️
#️ 2. Login Endpoint
#️

@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest):
    #️ find user by email
    user = await User.get_or_none(email=data.email)

    #️ check if user exists and password is correct
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    #️ create JWT token
    token = create_access_token(user.id)

    return TokenResponse(access_token=token)


#️
#️ 3. Current User Endpoint
#️

@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    #️ get_current_user already verified the token and loaded the user
    #️ we just return their info
    return UserResponse(id=user.id, username=user.username, email=user.email)