from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Project Nexus API"
    SECRET_KEY: str = "supersecretkeychangeinproduction"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours (with silent auto-refresh for active sessions)

    # Auth Security & Rate Limiting Settings
    AUTH_RATE_LIMIT_LOGIN: str = "10/minute"
    AUTH_RATE_LIMIT_REGISTER: str = "20/hour"
    ACCOUNT_LOCKOUT_MAX_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = 15

    # Database Settings
    # If DATABASE_URL is not set, we will fallback to sqlite
    DATABASE_URL: Optional[str] = None
    SQLITE_DATABASE_PATH: str = "./nexus.db"

    # API Keys
    GEMINI_API_KEY: Optional[str] = None
    
    # Razorpay Settings
    # If key and secret are missing, we default to local Sandbox/Mock Mode
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None
    RAZORPAY_WEBHOOK_SECRET: Optional[str] = None

    # Inventory Reservation Settings
    RESERVATION_EXPIRY_MINUTES: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
