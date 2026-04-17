import os

from dotenv import load_dotenv
from fastapi import FastAPI
from tortoise.contrib.fastapi import register_tortoise

load_dotenv()

# Tortoise connection URL example:
# - TiDB/MySQL: mysql://USER:PASSWORD@HOST:4000/DB_NAME?charset=utf8mb4
DATABASE_URL = os.environ["DATABASE_URL"]

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
        generate_schemas=True,
        add_exception_handlers=True,
    )
