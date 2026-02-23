from typing import Literal
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field, model_validator

class MCQRequest(BaseModel):
    """Body model for the /generate-mcq endpoint."""
    notes: str | None = Field(
        default=None,
        min_length=1,
        description="Raw notes to generate questions from."
    )

    deck_id: int | None = Field(
        default=None,
        ge=1, # greater than or equal to
        description="ID of the deck to use."
    )

    num_questions: int = Field(
        default=5,
        ge=1, # greater than or equal to
        le=50, # less than or equal to
        description="Number of MCQs to generate."
    )

    difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium",
        description="Difficulty level of the questions."
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

ai_route = APIRouter(prefix="/ai", tags=["AI"])

@ai_route.post("/generate-mcq")
async def generate_mcq(
    mcq_request: MCQRequest
) -> ORJSONResponse:
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
    