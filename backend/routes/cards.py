from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from deps.database import Card, Deck
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
