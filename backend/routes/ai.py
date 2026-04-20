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
        input_type="notes" if notes is not None else "deck",
        requested_count=num_questions,
        difficulty=difficulty,
        user=current_user,
        deck=deck,
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
                "raw_response": response.raw_response,
            }
        )
        await generation_run.save()

        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error: {response.error_message or 'Unknown error'}",
        )
    
    questions: list[MCQQuestion] = []
    for q in generated:
        question = q.question.strip()
        options = [q.option_a.strip(), q.option_b.strip(), q.option_c.strip(), q.option_d.strip()]
        correct_answer = q.correct_answer.strip().upper()
        explanation = q.explanation.strip() if q.explanation else None
        
        questions.append(
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
                generation_run=generation_run,
            )
        )
        
    if not questions:
        generation_run.update_from_dict(
            {
                "model_name": response.model_name,
                "status": "failed",
                "error_code": None,
                "error_message": "Gemini did not return any valid questions",
                "raw_response": response.raw_response,
            }
        )
        await generation_run.save()
        raise HTTPException(status_code=502, detail="Gemini did not return any valid questions")
    
    generation_run.update_from_dict(
        {
            "created_count": len(questions),
            "model_name": response.model_name,
            "status": "success",
            "error_code": None,
            "error_message": None,
            "raw_response": response.raw_response,
        }
    )
    await generation_run.save()

    await MCQQuestion.bulk_create(questions)

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
        for q in questions
    ]






# defines a class, integer for int, deck_id, string for question and bool for ai generated or not. 
class CardResponse(BaseModel):
    id: int
    deck_id: int
    question: str
    answer: str
    is_ai_generated: bool


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
) -> list[CardResponse]:
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
    generation_run = AIGenerationRun(
        kind="flashcard",
        input_type="notes",
        requested_count=cards_request.num_cards,
    )

    #unpacks the tuple into two variables, generated and response
    #await tells python to wait for background task to finish 
    # passes notes and desired number of cards
    generated, response = await gemini.generate_flashcards(
        notes=cards_request.notes,
        num_cards=cards_request.num_cards,
    )

    #checks if variable is empty, updates db 
    # logs what ai was being used, final status, specfic error code, error for humans to read 
    # commits the updated error info to db asynchronously
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
        # stops execution and sends 502 back 
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error: {response.error_message or 'Unknown error'}",
        )
    

    # initialises and empty list for new card objects 
    # loops through each ai generated flashcard, creates and saves a new record
    created_cards: list[Card] = []
    for fc in generated:
        card = await Card.create(
            question=fc.question,
            answer=fc.answer,
            deck_id=deck.id,
            is_ai_generated=True,
        )
         # adds the saved database object for it has an id to our list
        created_cards.append(card)
    
    # if loop if finished but empty, somethig went wrong, send 502
    if not created_cards:
        raise HTTPException(status_code=502, detail="Gemini did not return any correct flashcards")
    # udates the tracking to show it was successful
    generation_run.update_from_dict(
        {
            "model_name": response.model_name,
            "status": "success",
            "error_code": None,
            "error_message": None,
        }
    )
    # saves the tracking info to the database
    await generation_run.save()

    # uses a list comprehension to create a list of convert database object into card response. 
    return [
        CardResponse(
            id=card.id,
            deck_id=deck.id,
            question=card.question,
            answer=card.answer,
            is_ai_generated=card.is_ai_generated,
        )
        for card in created_cards
    ]



    


    
        

          
        