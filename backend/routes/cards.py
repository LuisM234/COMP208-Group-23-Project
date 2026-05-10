from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from deps.database import Card, Deck
from deps.leitner import review_card_leitner
from deps.security import get_current_user


#deck actions like create, list
#card actions like get, update, delete
deck_cards_route = APIRouter(prefix="/decks", tags=["Cards"])
cards_route = APIRouter(prefix="/cards", tags=["Cards"])



#pydantic schemas
class CardCreate(BaseModel):
    question: str
    answer: str


class CardUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None


class CardResponse(BaseModel):
    id: int
    deck_id: int
    question: str
    answer: str
    is_ai_generated: bool



#helpers
async def get_deck_for_user(deck_id: int, user_id: int) -> Deck:
    """Fetch a deck that belongs to the current user.

    Returns 404 rather than 403 to avoid leaking whether a deck ID exists.
    """
    deck = await Deck.get_or_none(id=deck_id, user_id=user_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck


async def get_card_for_user(card_id: int, user_id: int) -> Card:
    """Fetch a card whose deck belongs to the current user.

    Joins through the deck to verify ownership in a single query.
    Returns 404 rather than 403 to avoid leaking whether a card ID exists.
    """
    card = await Card.get_or_none(id=card_id, deck__user_id=user_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card



#creates a card
@deck_cards_route.post("/{deck_id}/cards", response_model=CardResponse, status_code=201)
async def create_card(
    deck_id: int,
    payload: CardCreate,
    user=Depends(get_current_user),
):
    """Create a new manual flashcard inside a deck owned by the current user."""
    # Ownership check first – raises 404 if deck doesn't belong to user
    deck = await get_deck_for_user(deck_id, user.id)

    card = await Card.create(
        question=payload.question,
        answer=payload.answer,
        is_ai_generated=False,
        deck_id=deck.id,
    )
    return CardResponse(
        id=card.id,
        deck_id=deck.id,
        question=card.question,
        answer=card.answer,
        is_ai_generated=card.is_ai_generated,
    )



#lists all cards in a deck
@deck_cards_route.get("/{deck_id}/cards", response_model=list[CardResponse])
async def list_cards(
    deck_id: int,
    user=Depends(get_current_user),
):
    """List every card inside a deck owned by the current user."""
    # Ownership check first – raises 404 if deck doesn't belong to user
    deck = await get_deck_for_user(deck_id, user.id)

    cards = await Card.filter(deck_id=deck.id).all()
    return [
        CardResponse(
            id=c.id,
            deck_id=deck.id,
            question=c.question,
            answer=c.answer,
            is_ai_generated=c.is_ai_generated,
        )
        for c in cards
    ]


#fetches a single card
@cards_route.get("/{card_id}", response_model=CardResponse)
async def get_card(
    card_id: int,
    user=Depends(get_current_user),
):
    """Get a single card by ID (only if it belongs to one of the user's decks)."""
    card = await get_card_for_user(card_id, user.id)
    return CardResponse(
        id=card.id,
        deck_id=card.deck_id,
        question=card.question,
        answer=card.answer,
        is_ai_generated=card.is_ai_generated,
    )



#update card
@cards_route.put("/{card_id}", response_model=CardResponse)
async def update_card(
    card_id: int,
    payload: CardUpdate,
    user=Depends(get_current_user),
):
    """Update a card's question and/or answer text."""
    card = await get_card_for_user(card_id, user.id)

    if payload.question is not None:
        card.question = payload.question
    if payload.answer is not None:
        card.answer = payload.answer
    await card.save()

    return CardResponse(
        id=card.id,
        deck_id=card.deck_id,
        question=card.question,
        answer=card.answer,
        is_ai_generated=card.is_ai_generated,
    )


#deletes a card
@cards_route.delete("/{card_id}", status_code=204)
async def delete_card(
    card_id: int,
    user=Depends(get_current_user),
):
    """Delete a card (study progress cascades via the DB foreign key)."""
    card = await get_card_for_user(card_id, user.id)
    await card.delete()


# ---------------------------------------------------------------------------
# Review endpoint — wires the study session UI into the Leitner scheduler.
# ---------------------------------------------------------------------------
# The frontend (study_session.html) POSTs here with a 1-4 rating per card.
# We map that to a Leitner correct/incorrect signal, then delegate the heavy
# lifting (schedule update, daily aggregates, ReviewEvent row) to leitner.py.

class CardReviewRequest(BaseModel):
    # 1 = Again, 2 = Hard, 3 = Good, 4 = Easy (matches study_session.html buttons)
    rating: int
    # Optional client-reported response time in milliseconds.
    response_time_ms: Optional[int] = None


class CardReviewResponse(BaseModel):
    card_id: int
    correct: bool
    new_box: int
    next_review: datetime
    streak: int


@cards_route.post("/{card_id}/review", response_model=CardReviewResponse)
async def review_card(
    card_id: int,
    payload: CardReviewRequest,
    user=Depends(get_current_user),
):
    """Record a card review and advance the Leitner schedule.

    Maps the 1-4 rating from the study session UI to the boolean `correct`
    signal the Leitner module expects: `Again` (1) counts as incorrect,
    everything else counts as correct.
    """
    if payload.rating not in (1, 2, 3, 4):
        raise HTTPException(
            status_code=400,
            detail="rating must be 1 (Again), 2 (Hard), 3 (Good), or 4 (Easy)",
        )

    correct = payload.rating >= 2

    try:
        progress = await review_card_leitner(
            user_id=user.id,
            card_id=card_id,
            correct=correct,
            response_time_ms=payload.response_time_ms,
        )
    except ValueError:
        # Card with the given id does not exist.
        raise HTTPException(status_code=404, detail="Card not found")
    except PermissionError:
        # Card exists but belongs to someone else. Return 404 so we don't
        # leak the existence of other users' cards.
        raise HTTPException(status_code=404, detail="Card not found")

    return CardReviewResponse(
        card_id=card_id,
        correct=correct,
        new_box=progress.box,
        next_review=progress.next_review,
        streak=progress.streak,
    )
