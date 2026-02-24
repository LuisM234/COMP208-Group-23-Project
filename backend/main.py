from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from routes.ai import ai_route
from routes.decks import decks_route

app = FastAPI(
    title="Flashcards API",
    description="API for the flashcards project.",
    # speeds up responses from the API
    default_response_class=ORJSONResponse,
)

app.include_router(ai_route)
app.include_router(decks_route)