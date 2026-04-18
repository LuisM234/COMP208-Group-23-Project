from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, RedirectResponse
from routes.ai import ai_route
from routes.decks import decks_route
from routes.cards import deck_cards_route, cards_route
from deps.model import register_database
from routes.auth import router as auth_route
from routes.analytics import router as analytics_route

app = FastAPI(
    title="Flashcards API",
    description="API for the flashcards project.",
    # speeds up responses from the API
    default_response_class=ORJSONResponse,
)
register_database(app)

# send to docs if root is accessed
@app.get("/")
async def root():
    return RedirectResponse(url="/docs")

from fastapi.middleware.cors import CORSMiddleware

# allows front end to connect to API 
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:5501",
        "http://127.0.0.1:5501",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "null",  # allows file:// origin (browsers send Origin: null for local files)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_route)
app.include_router(decks_route)
app.include_router(deck_cards_route)   
app.include_router(cards_route)       
app.include_router(auth_route, prefix="/auth", tags=["Auth"])
app.include_router(analytics_route)
