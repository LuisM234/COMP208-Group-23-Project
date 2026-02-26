import orjson
import asyncio
from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field, model_validator
from google import genai
from google.genai import errors, types



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
        default=None,
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

    # cant do this now according to big mo
    async def get_current_user(request: Request) -> Any:
        """Get current authenticated user from the request. Raises 401 if not authenticated."""
        # we have a function to get the current user from the request,if not autheticated say not authorised
        # mo: not implemented yet, we'll come back to this later
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(status_code=401, detail="Unauthorised")
        return user

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



    class GeminiWrapper: 
        """ Async gemini wrapper class, to call gemini api, and return the response, we can use this in our endpoints to call gemini and get the response, then parse it and return it to the client, using aiohttp"""

        def __init__(
            self,
            api_key: str,
            model: str = "gemini-3.0-flash",
            api_version: str = "v1alpha",
        ):
            self.api_key = api_key
            self.model = model
            self.api_version = api_version
        

        async def generate_flashcards(self, notes: str, num_cards: int) -> list[dict[str, str]]:
            prompt = f"""
You generate study flashcards from notes.
Return ONLY a JSON array with exactly {num_cards} items.
Each item must be an object with:
- "question"
- "answer"


NOTES:
{notes}
""".strip()
            config = types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            )
            # makes a config object for model, and chooses a temp ( randomness level) make it more deterministic and focused for flashcards
            # explicitly tells gemini to return the data in valid JSON format
            #configures network settings 
            # specifies which api version to use
            # also stores empty dictionary for extra arguments like custom headers or timeouts


            http_options = types.HttpOptions(
                api_version=self.api_version,
                async_client_args={},
            )
            # starts a block for catching netowrk or api errors
            # then intialises the client and creates a session and closes when block finishes
            # the await aclient.model is used for network call, tells python to run other task while waiting fro gemini to finish generating the flashcards
            try:
                async with genai.Client(
                    api_key=self.api_key,
                    http_options=http_options,
                ).aio as aclient:
                    response = await aclient.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=config,
                    )
            #catches errors by googles servers
            #extracts the http code from error object 
            # 429 for checking if you have exceeded your rate limit, if hit raises and error for end user to see
            #from none is used to cleanup the traceback of previosu internal errors
            # then a standard exception for catching all other unexpected issues, so app doesn't crash silently 
            

            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code == status.HTTP_429_TOO_MANY_REQUESTS:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Gemini rate limit exceeded",
                    ) from None
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gemini error ({code})",
                ) from None
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to contact Gemini",
                ) from None
        