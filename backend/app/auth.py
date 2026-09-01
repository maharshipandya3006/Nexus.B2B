from datetime import datetime, timedelta
from typing import Optional
import jwt
from jwt.exceptions import InvalidTokenError
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from . import models

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")

def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8') if isinstance(hashed_password, str) else hashed_password
    )

def get_password_hash(password: str) -> str:
    # 12 rounds provides industry-grade resistance against hardware brute-force
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

import uuid

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    now = datetime.utcnow()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": str(uuid.uuid4())
    })
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_token_payload(token: str, verify_exp: bool = True) -> Optional[dict]:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": verify_exp}
        )
    except Exception:
        return None

def get_user_from_token(token: str, db: Session) -> Optional[models.User]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            return None
        return db.query(models.User).filter(models.User.username == username).first()
    except Exception:
        return None

def refresh_user_token(token: str, db: Session) -> Optional[dict]:
    """
    Decodes the token (permitting expired tokens within a grace window of 30 days)
    and verifies the user exists and is valid, then issues a fresh token.
    """
    payload = decode_token_payload(token, verify_exp=False)
    if not payload:
        return None
    username: str = payload.get("sub")
    if not username:
        return None
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        return None

    # Check that it hasn't expired by more than 30 days if exp claim exists
    exp = payload.get("exp")
    if exp:
        exp_dt = datetime.utcfromtimestamp(exp)
        if datetime.utcnow() > exp_dt + timedelta(days=30):
            return None

    new_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": new_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username
    }

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = get_user_from_token(token, db)
    if user is None:
        raise credentials_exception
    return user
