# app/config.py
import os
from dotenv import load_dotenv
from pydantic import BaseSettings
load_dotenv()  # load environment variables from .env

JWT_SECRET = os.getenv("JWT_SECRET", "change_this_secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15))

DATABASE_URL = os.getenv("DATABASE_URL")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", 8000))


class Settings(BaseSettings):
    SECRET_KEY: str = os.getenv("CHAT_JWT_SECRET")
    ALGORITHM: str = "HS256"

settings = Settings()