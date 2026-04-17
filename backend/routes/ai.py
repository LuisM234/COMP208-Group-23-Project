from typing import Any, Literal

import orjson
from fastapi import APIRouter, HTTPException, Request, Depends
from deps.gemini import GeminiWrapper, get_gemini_wrapper
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field, model_validator
from deps.security import get_current_user
from deps.database import Card, Deck, User
from deps.gemini import Flashcard

class MCQRequest(BaseModel):
    """Body model for the /generate-mcq endpoint."""

    notes: str | None = Field(
        default=None, min_length=1, description="Raw notes to generate questions from."
    )

    deck_id: int | None = Field(
        default=None,
        ge=1,  # greater than or equal to
        description="ID of the deck to use.",
    )

    num_questions: int = Field(
        default=5,
        ge=1,  # greater than or equal to
        le=50,  # less than or equal to
        description="Number of MCQs to generate.",
    )

    difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium", description="Difficulty level of the questions."
    )

    @model_validator(mode="after")
    def validate_source(self) -> "MCQRequest":
        """Ensures that either notes or deck_id is provided, but not both."""
        has_notes = self.notes is not None
        has_deck = self.deck_id is not None

        if has_notes and has_deck:
            raise ValueError("Provide either notes or deck_id, not both")
        if not has_notes and not has_deck:
            raise ValueError("Provide either notes or deck_id")
        return self
    
class GenerateCardsRequest(BaseModel):
    # we make the body model for generate-cards endpoint

    notes: str | None = Field(
        default=None,
        min_length=1,
        description="this for notes to generate flashcards from",
    )

    deck_id: int | None = Field(
        default=None,
        ge=1,  # greater than or equal to
        description="ID of the deck to add cards into",
    )

    num_cards: int = Field(
        default=5,
        ge=1,
        le=50,
        description="number of flashcards to generate",
    )

    @model_validator(mode="after")
    def validate_source(self) -> "GenerateCardsRequest":
        # makes sure notes and deck_id are both provided or both not provided
        if self.notes is None or not self.notes.strip():
            raise ValueError("provide non-empty notes")
        if self.deck_id is None:
            raise ValueError("provide deck_id")
        return self

    

    # this would parse the json array of a question and answer from the gemini output.
    def parse_flashcards_json(raw_text: str, max_cards: int) -> list[dict[str, str]]:
        """Parse Gemini response JSON to extract flashcards.

        Parameters
        ----------
        raw_text : str
            The raw JSON string returned by Gemini.
        max_cards : int
            The maximum number of flashcards to return.

        Returns
        -------
        list[dict[str, str]]
            A list of flashcards, each represented as a dictionary with 'question' and 'answer' keys.
        """

        parsed: Any
        try:
            parsed = orjson.loads(raw_text)
        except orjson.JSONDecodeError:
            raise ValueError("Gemini response is not valid JSON") from None

        # gemini didn't return a json array, raise an error
        if not isinstance(parsed, list):
            raise ValueError("Gemini didn't return a JSON array")

        # creates empty list, to store final flashcards, check if in a dictionary, if its not in dictionary skip to next one
        # then attempts tp pull value for question and answer key
        # double checks if are string, if aren't strings, go to next one, also clear whitespaces
        # if blank gets skipped,
        # final cleaned card, gets added to cards list, then would return it
        cards: list[dict[str, str]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue

            question = item.get("question")
            answer = item.get("answer")
            if not isinstance(question, str) or not isinstance(answer, str):
                continue

            question = question.strip()
            answer = answer.strip()
            if not question or not answer:
                continue
            cards.append({"question": question, "answer": answer})

        if not cards:
            raise ValueError("No valid flashcards found in Gemini response")
        return cards[:max_cards]


ai_route = APIRouter(prefix="/ai", tags=["AI"])


@ai_route.post("/generate-mcq")
async def generate_mcq(mcq_request: MCQRequest) -> ORJSONResponse:
    """Generate exam-style multiple choice questions using Gemini.

    Request Body:
    - **notes** (`str | None`)
    Raw notes to generate questions from. Required if `deck_id` is not provided.

    - **deck_id** (`int | None`)
    ID of the deck whose cards will be used as input. Required if `notes` is not provided.

    - **num_questions** (`int`, default=5)
    Number of questions to generate.

    - **difficulty** (`"easy" | "medium" | "hard"`, default="medium")
    Difficulty level of the generated questions.
    """
    return ORJSONResponse(content={"message": "ok"})
    

# defines a POST endpoint at /generate-cards
# validates incoming JSON againts GenerateCardsRequest schema
# ensures the user is logged in ( this would be the dependency injection)
# mo will fix orjson respones stuff
# after the actual generation logic of teh flashcards
@ai_route.post("/generate-cards")
async def generate_cards(
    cards_request: GenerateCardsRequest,
    current_user: User = Depends(get_current_user),
    gemini: GeminiWrapper = Depends(get_gemini_wrapper),
) -> ORJSONResponse:
    """Generate flashcards from notes or a deck using Gemini.

    Request Body:
    - **notes** (`str | None`)
    Raw notes to generate flashcards from. Required if `deck_id` is not provided.

    - **deck_id** (`int | None`)
    ID of the deck whose cards will be used as input. Required if `notes` is not provided.

    - **num_cards** (`int`, default=5)
    Number of flashcards to generate.
    """

    # Got to make sure the logic for deck is there
    deck = await Deck.filter(id=cards_request.deck_id, user_id=current_user.id).first()
    if deck is None:
        raise HTTPException(status_code=404, detail="Deck not found or you do not have access to it",
        )
    

    #make a variable to store flashcards
    # await tells the program to stop specific task to let other taks run unitl ai finishes generating the cards
    # notes is from the request body, num_cards is also from the request body, we would pass these to the gemini wrapper which would call the gemini api and return a list of flashcards
    flashcards: list [Flashcard] = await gemini.generate_flashcards(
        notes=cards_request.notes,
        num_cards=cards_request.num_cards,
    )


    # initialise an empty list to store the database object we make
    # start loop to go through each flashcard we got from gemini, and create a new card in the database for each one, with the question and answer from the flashcard,
    #  and the deck_id from the request body, also set is_ai_generated to true since these are generated by ai
    # then add the finished flashcard to created cards
    created_cards = list[Card] = []
    for fc in flashcards:
        card = await card.create(
            question=fc.question,
            answer=fc.answer,
            deck_id=deck.id,
            is_ai_generated=True,
        )
        created_cards.append(card)

    # returns an orjson response 
    return ORJSONResponse(
        # will contain a list of card objects
        # unique id for card, question, answer, deck_id, and is_ai_generated boolean
        content={
            "cards": [
                {
                    "id": card.id,
                    "question": card.question,
                    "answer": card.answer,
                    "deck_id": card.deck_id,
                    "is_ai_generated": card.is_ai_generated,
                }
                # loop thorugh each card in created_cards list
                for card in created_cards
            ]
        }
    )


    
        

          
        