from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, RedirectResponse
from routes.ai import ai_route
from routes.decks import decks_route
from deps.model import register_database
from routes.auth import router as auth_route
from routes.analytics import router as analytics_route

app = FastAPI(
    title="Flashcards API",
    description="API for the flashcards project.",
    # speeds up responses from the API
    default_response_class=ORJSONResponse,
)


# send to docs if root is accessed
@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


app.include_router(ai_route)
app.include_router(decks_route)
app.include_router(auth_route, prefix="/auth", tags=["Auth"])
app.include_router(analytics_route)
