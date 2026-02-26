from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, RedirectResponse
from routes.ai import ai_route
from routes.decks import decks_route

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
