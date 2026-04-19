from typing import Any, Literal

import orjson
from fastapi import APIRouter, HTTPException, Depends
from deps.gemini import GeminiWrapper, get_gemini_wrapper
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field, model_validator, field_validator
from deps.security import get_current_user
from deps.database import Card, Deck, User, MCQQuestion, AIGenerationRun
from deps.gemini import Flashcard
from deps.gemini import GeminiHTTPException

class MCQRequest(BaseModel):
    """Body model for the /generate-mcq endpoint."""
    
    deck_id: int = Field(
        ge=1,  # greater than or equal to
        description="ID of the deck to use.",
    )

    notes: str | None = Field(
        default=None, 
        min_length=1, 
        description="Raw notes to generate questions from. If not provided, the deck's cards are used."
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

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str | None) -> str | None:
        """Ensures that if notes is provided, it is not just whitespace."""
        if value is None:
            return None

        value = value.strip()
        if not value:
            raise ValueError("Provide non-empty notes")

        return value
    
class MCQQuestionResponse(BaseModel):
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    explanation: str
    difficulty: str


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
async def generate_mcq(
    mcq_request: MCQRequest, 
    current_user: User = Depends(get_current_user),
    gemini_wrapper: GeminiWrapper = Depends(get_gemini_wrapper)
) -> list[MCQQuestionResponse]:
    """Generate exam-style multiple choice questions using Gemini.

    Request Body:
    - **notes** (`str | None`)
    Raw notes to generate questions from.

    - **deck_id** (`int`)
    ID of the deck whose cards will be used as input.

    - **num_questions** (`int`, default=5)
    Number of questions to generate.

    - **difficulty** (`"easy" | "medium" | "hard"`, default="medium")
    Difficulty level of the generated questions.
    """
    notes = mcq_request.notes
    deck_id = mcq_request.deck_id
    num_questions = mcq_request.num_questions
    difficulty = mcq_request.difficulty
    
    deck = await current_user.decks.filter(id=deck_id).first()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    
    if notes is not None:
        source_notes = notes
    else:
        deck_cards = await deck.cards.filter(is_ai_generated=False).all()
        if not deck_cards:
            raise HTTPException(status_code=400, detail="Deck has no cards to use as source material")
        
        source_notes = "\n\n".join(
            f"Q: {card.question}\nA: {card.answer}"
            for card in deck_cards
        )
        
    generation_run = AIGenerationRun(
        kind="mcq",
        input_type="notes" if notes else "deck",
        requested_count=num_questions,
        difficulty=difficulty,
    )

    generated, response = await gemini_wrapper.generate_mcq_questions(
        notes=source_notes,
        num_questions=num_questions,
        difficulty=difficulty,
    )
    if generated is None:
        generation_run.update_from_dict(
            {
                "model_name": response.model_name,
                "status": response.status,
                "error_code": response.error_code,
                "error_message": response.error_message,
            }
        )
        await generation_run.save()

        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error: {response.error_message or 'Unknown error'}",
        )
    
    valid_questions: list[MCQQuestion] = []
    for q in generated:
        question = q.question.strip()
        options = [q.option_a.strip(), q.option_b.strip(), q.option_c.strip(), q.option_d.strip()]
        correct_answer = q.correct_answer.strip().upper()
        explanation = q.explanation.strip() if q.explanation else None
        
        valid_questions.append(
            MCQQuestion(
                question=question,
                option_a=options[0],
                option_b=options[1],
                option_c=options[2],
                option_d=options[3],
                correct_answer=correct_answer,
                explanation=explanation,
                difficulty=difficulty,
                deck=deck,
            )
        )
        
    if not valid_questions:
        raise HTTPException(status_code=502, detail="Gemini did not return any valid questions")
    
    await MCQQuestion.bulk_create(valid_questions)
    generation_run.update_from_dict(
        {
            "model_name": response.model_name,
            "status": "success",
            "error_code": None,
            "error_message": None,
        }
    )
    await generation_run.save()

    return [
        MCQQuestionResponse(
            question=q.question,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_answer=q.correct_answer,
            explanation=q.explanation,
            difficulty=q.difficulty,
        )
        for q in valid_questions
    ]
    

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
    try:
        flashcards, generation_run = await gemini.generate_flashcards(
            notes=cards_request.notes,
            num_cards=cards_request.num_cards,
            user_id=current_user.id,
            deck_id=deck.id,
        )
    except GeminiHTTPException:
        raise

    



    # initialise an empty list to store the database object we make
    # start loop to go through each flashcard we got from gemini, and create a new card in the database for each one, with the question and answer from the flashcard,
    #  and the deck_id from the request body, also set is_ai_generated to true since these are generated by ai
    # then add the finished flashcard to created cards
    created_cards : list[Card] = []
    for fc in flashcards:
        card = await Card.create(
            question=fc.question,
            answer=fc.answer,
            deck_id=deck.id,
            is_ai_generated=True,
            generation_run_id=generation_run.id,
        )
        created_cards.append(card)
    return created_cards


    
        

          
        