#️ security.py includes:
#️ 1. password hashing
#️ 2. JWT creation and verification
#️ 3. current user dependency
#️ 4. token parsing

import os
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from deps.database import User

# Config
pwd_context = CryptContext(schemes=["bcrypt"])
SECRET_KEY = os.getenv("SECRET_KEY", "dev-fallback-key")
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


#️
#️ 1. Password hashing and verification
#️

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


#️
#️ 2. JWT creation and verification
#️

def create_access_token(user_id: int) -> str:
    #️ creates a JWT token with user_id and expiration time
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_access_token(token: str) -> int:
    #️ decodes the JWT token and returns the user_id
    #️ raises JWTError if token is invalid or expired
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return int(payload["sub"])


#️
#️ 3. Current user dependency & 4. Token parsing
#️

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    #️ extracts token from request header
    #️ verifies token and loads user from database
    #️ rejects request if token is invalid or user not found

    try:
        user_id = verify_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await User.get_or_none(id=user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user