from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from deps.database import Deck
from deps.security import get_current_user
from datetime import datetime
from deps.leitner import get_due_study_progress, initialise_progress_for_deck

decks_route = APIRouter(prefix="/decks", tags=["Decks"])



# Pydantic schemas


class DeckCreate(BaseModel):
    title: str
    description: Optional[str] = ""

class DeckUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

class DeckResponse(BaseModel):
    id: int
    title: str
    description: str

class DeckMCQsResponse(BaseModel):
    id: int

    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    
    correct_answer: str
    explanation: str | None = None
    difficulty: str | None = None
    
    created_at: datetime


# Helper


async def get_deck_for_user(deck_id: int, user_id: int) -> Deck:
    """Fetch a deck by ID that belongs to the current user.

    Returns 404 rather than 403 to avoid leaking whether a deck ID exists.
    """
    deck = await Deck.get_or_none(id=deck_id, user_id=user_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck



# Routes


@decks_route.post("/", response_model=DeckResponse, status_code=201)
async def create_deck(payload: DeckCreate, user=Depends(get_current_user)):
    """Create a new deck for the logged-in user."""
    deck = await Deck.create(
        title=payload.title,
        description=payload.description or "",
        user_id=user.id,
    )
    return DeckResponse(id=deck.id, title=deck.title, description=deck.description)


@decks_route.get("/", response_model=list[DeckResponse])
async def list_decks(user=Depends(get_current_user)):
    """List all decks belonging to the logged-in user."""
    decks = await Deck.filter(user_id=user.id).all()
    return [DeckResponse(id=d.id, title=d.title, description=d.description) for d in decks]


@decks_route.get("/{deck_id}", response_model=DeckResponse)
async def get_deck(deck_id: int, user=Depends(get_current_user)):
    """Get a single deck (only if it belongs to the logged-in user)."""
    deck = await get_deck_for_user(deck_id, user.id)
    return DeckResponse(id=deck.id, title=deck.title, description=deck.description)

@decks_route.get("/{deck_id}/mcqs")
async def get_deck_mcqs(deck_id: int, user=Depends(get_current_user)) -> list[DeckMCQsResponse]:
    """Get a list of all MCQs in a deck.
    
    Request Body:
    - **deck_id**: (`int`)
    The ID of the deck to fetch MCQs from.
    """
    deck = await get_deck_for_user(deck_id, user.id)
    mcqs = await deck.mcq_questions.all()
    return [
        DeckMCQsResponse(
            id=mcq.id,
            question=mcq.question,
            option_a=mcq.option_a,
            option_b=mcq.option_b,
            option_c=mcq.option_c,
            option_d=mcq.option_d,
            correct_answer=mcq.correct_answer,
            explanation=mcq.explanation,
            difficulty=mcq.difficulty,
            created_at=mcq.created_at
        ) 
        for mcq in mcqs
    ]

@decks_route.put("/{deck_id}", response_model=DeckResponse)
async def update_deck(deck_id: int, payload: DeckUpdate, user=Depends(get_current_user)):
    """Update a deck's title and/or description."""
    deck = await get_deck_for_user(deck_id, user.id)
    if payload.title is not None:
        deck.title = payload.title
    if payload.description is not None:
        deck.description = payload.description
    await deck.save()
    return DeckResponse(id=deck.id, title=deck.title, description=deck.description)


@decks_route.delete("/{deck_id}", status_code=204)
async def delete_deck(deck_id: int, user=Depends(get_current_user)):
    """Delete a deck (cards cascade-delete via the DB foreign key)."""
    deck = await get_deck_for_user(deck_id, user.id)
    await deck.delete()

class DueCardResponse(BaseModel):
    id: int
    question: str
    answer: str
    box: int
    next_review: datetime

@decks_route.get("/{deck_id}/due", response_model=list[DueCardResponse])
async def get_due_cards(deck_id: int, user=Depends(get_current_user)):
    await get_deck_for_user(deck_id, user.id)
    await initialise_progress_for_deck(user_id=user.id, deck_id=deck_id)
    
    from deps.database import StudyProgress, Card
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)

    # Debug: check all progress rows regardless of due date
    all_rows = await StudyProgress.filter(
        user_id=user.id,
        card__deck_id=deck_id,
    ).prefetch_related("card").all()
    
    for r in all_rows:
        print(f"Card {r.card.id}: box={r.box}, next_review={r.next_review}, now={now}, due={r.next_review <= now}")

    progress_rows = await StudyProgress.filter(
        user_id=user.id,
        card__deck_id=deck_id,
        next_review__lte=now,
    ).prefetch_related("card").all()
    
    return [
        DueCardResponse(
            id=p.card.id,
            question=p.card.question,
            answer=p.card.answer,
            box=p.box,
            next_review=p.next_review,
        )
        for p in progress_rows
    ]

@decks_route.get("/{deck_id}/cram", response_model=list[DueCardResponse])
async def get_cram_cards(deck_id: int, user=Depends(get_current_user)):
    """Return ALL cards in the deck regardless of schedule — for cram mode."""
    await get_deck_for_user(deck_id, user.id)
    from deps.database import Card
    cards = await Card.filter(deck_id=deck_id).all()
    return [
        DueCardResponse(
            id=c.id,
            question=c.question,
            answer=c.answer,
            box=0,
            next_review=datetime.now(timezone.utc),
        )
        for c in cards
    ]


@decks_route.get("/{deck_id}/progress")
async def get_deck_progress(deck_id: int, user=Depends(get_current_user)):
    """Return study progress for all cards in a deck, regardless of due date."""
    await get_deck_for_user(deck_id, user.id)
    from deps.database import StudyProgress
    rows = await StudyProgress.filter(
        user_id=user.id,
        card__deck_id=deck_id,
    ).prefetch_related("card").all()
    return [
        {
            "card_id": p.card.id,
            "box": p.box,
            "last_reviewed": p.last_reviewed.isoformat() if p.last_reviewed else None,
            "next_review": p.next_review.isoformat() if p.next_review else None,
        }
        for p in rows
    ]