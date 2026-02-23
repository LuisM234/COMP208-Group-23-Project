from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from routes.ai import ai_route

app = FastAPI(
    title="Flashcards API",
    description="API for the flashcards project.",
    # speeds up responses from the API
    default_response_class=ORJSONResponse,
)

app.include_router(ai_route)