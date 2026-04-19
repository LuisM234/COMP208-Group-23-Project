import os
from typing import cast

from fastapi import HTTPException, status
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError


from deps.database import AIGenerationRun


class Flashcard(BaseModel):
    """Model for a flashcard with a question and answer."""

    question: str
    answer: str
    
class GeneratedMCQ(BaseModel):
    """Model for a multiple-choice question with options and the correct answer."""

    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str

    correct_answer: str
    explanation: str
    
class GeminiResponse(BaseModel):
    model_name: str
    status: str
    error_code: int | None
    error_message: str | None
    raw_response: str | None


class GeminiHTTPException(HTTPException):
    """HTTPException that also carries the saved AIGenerationRun audit record."""

    def __init__(self, status_code: int, detail: str, run: "AIGenerationRun"):
        super().__init__(status_code=status_code, detail=detail)
        self.run = run

class GeminiWrapper:
    """Async Gemini wrapper class to create custom callbacks and handle responses.

    We can use this in our endpoints to call Gemini and get the response,
    then parse it and return it to the client, using aiohttp.

    Parameters
    ----------
    api_key : str
        The API key for authenticating with the Gemini API.
    model : str, optional
        The Gemini model to use for generating content (default is "gemini-3.0-flash").
    api_version : str, optional
        The version of the Gemini API to use (default is "v1").
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.0-flash",
        api_version: str = "v1",
    ):
        self.api_key = api_key
        self.model = model
        self.api_version = api_version

    async def generate_flashcards(
        self, notes: str, num_cards: int
    ) -> list[Flashcard]:
        """Generates flashcards from notes using Gemini API.
        
        Parameters
        ----------
        notes : str
            The raw notes to generate flashcards from.
        num_cards : int
            The number of flashcards to generate.
            
        Returns
        -------
        list[Flashcard]
            A list of generated flashcards. Each flashcard contains a question and an answer.
        """


        config = types.GenerateContentConfig(
            system_instruction=f"You generate study flashcards from notes. Return exactly {num_cards} items.",
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=list[Flashcard],
        )
        # makes a config object for model, and chooses a temp ( randomness level) make it more deterministic and focused for flashcards
        # explicitly tells gemini to return the data in valid JSON format
        # configures network settings
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
                    contents=notes,
                    config=config,
                )
        # catches errors by googles servers
        # extracts the http code from error object
        # 429 for checking if you have exceeded your rate limit, if hit raises and error for end user to see
        # from none is used to cleanup the traceback of previosu internal errors
        # then a standard exception for catching all other unexpected issues, so app doesn't crash silently
        except errors.APIError as exc:
            code = exc.code
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

        # tries to get text from response, returns none if doesn't exist
        # checks if text is missing, not a string or contains only whitespaces
        # check the nested structure ( candidates -> f candidate -> f part -> text)
        # if manual fails the response fails, the response is invalid or unexpected
        # the none gets rid of the traceback of caught exception
        model_text = response.text
        if not model_text or not model_text.strip():
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Not expected response from Gemini",
            )

        if not response.parsed:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini response is not valid JSON",
            )

        parsed_cards = cast(list[Flashcard], response.parsed)
        return parsed_cards
    
    async def generate_mcq_questions(
        self,
        notes: str,
        num_questions: int,
        difficulty: str,
    ) -> tuple[list[GeneratedMCQ] | None, GeminiResponse]:
        """Generates multiple-choice questions from notes using Gemini API.
        
        Parameters
        ----------
        notes : str
            The raw notes to generate questions from.
        num_questions : int
            The number of questions to generate.
        difficulty : str
            The difficulty level of the questions (e.g., "easy", "medium", "hard").
        """
        config = types.GenerateContentConfig(
            system_instruction=(
                f"You generate exam-style multiple choice questions from notes. "
                f"Return exactly {num_questions} items. Correct answer should be one of the lettered options. "
                f"Difficulty level: {difficulty}."
            ),
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=list[GeneratedMCQ],
        )

        http_options = types.HttpOptions(
            api_version=self.api_version,
            async_client_args={},
        )

        try:
            async with genai.Client(
                api_key=self.api_key,
                http_options=http_options,
            ).aio as aclient:
                response = await aclient.models.generate_content(
                    model=self.model,
                    contents=notes,
                    config=config,
                )
        except errors.APIError as exc:
            status_name = (
                "rate_limited"
                if exc.code == status.HTTP_429_TOO_MANY_REQUESTS
                else "failed"
            )
            return None, GeminiResponse(
                model_name=self.model,
                status=status_name,
                error_code=exc.code,
                error_message=exc.message,
                raw_response=str(exc.response)
            )

        except Exception as exc:
            return None, GeminiResponse(
                model_name=self.model,
                status="failed",
                error_code=None,
                error_message="Unknown error occurred while contacting Gemini",
                raw_response=str(exc),
            )

        raw_text = response.text
        if not raw_text or not raw_text.strip():
            return None, GeminiResponse(
                model_name=self.model,
                status="failed",
                error_code=None,
                error_message="Empty response from Gemini",
                raw_response=raw_text,
            )
        
        parsed = response.parsed
        if not parsed:
            return None, GeminiResponse(
                model_name=self.model,
                status="invalid_json",
                error_code=None,
                error_message="Gemini response is not valid JSON",
                raw_response=raw_text,
            )
            
        try:
            validated = [
                GeneratedMCQ.model_validate(item) 
                for item in cast(list[object], parsed)
            ]
        except ValidationError as exc:
            return None, GeminiResponse(
                model_name=self.model,
                status="invalid_json",
                error_code=None,
                error_message=f"Schema validation failed: {exc}",
                raw_response=raw_text,
            )
            
        if len(validated) != num_questions:
            return None, GeminiResponse(
                model_name=self.model,
                status="invalid_json",
                error_code=None,
                error_message=f"Expected {num_questions} questions, got {len(validated)}",
                raw_response=raw_text,
            )

        return validated, GeminiResponse(
            model_name=self.model,
            status="success",
            error_code=None,
            error_message=None,
            raw_response=raw_text,
        )

# a depenency function to show the gemin wrapper
# checks if the api for two environment variable names
# if no key is found, so server will not work, so raise a 500 server error,
# gets model ( not decided), providing defaults if are not set.
# then finally returns the isntance of Gemini wrapper class
def get_gemini_wrapper() -> GeminiWrapper:
    """Dependency function to get an instance of GeminiWrapper with API key from environment variables."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gemini API key not configured",
        )

    model = os.getenv("GEMINI_MODEL", "gemini-3.0-flash")
    api_version = os.getenv("GEMINI_API_VERSION", "v1")
    return GeminiWrapper(api_key=api_key, model=model, api_version=api_version)
