import os

from dotenv import load_dotenv
from fastapi import FastAPI
from tortoise.contrib.fastapi import register_tortoise

load_dotenv()

# Tortoise connection URL examples:
# - TiDB/MySQL: mysql://USER:PASSWORD@HOST:4000/DB_NAME?charset=utf8mb4
# - SQLite (local fallback): sqlite://./flashcards.db
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite://./flashcards.db")

TORTOISE_ORM = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        "models": {
            "models": ["deps.database"],
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}


def register_database(app: FastAPI) -> None:
    register_tortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=False,
        add_exception_handlers=True,
    )
