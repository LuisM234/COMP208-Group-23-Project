import json
import os
import re
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


def _parse_json_array(raw_text: str) -> list[object]:
    """Parse a JSON array even if Gemini wraps it in markdown fences."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if not match:
            raise
        data = json.loads(match.group(0))

    if not isinstance(data, list):
        raise ValueError("Gemini response must be a JSON array")

    return data

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
    ) -> tuple[list[Flashcard] | None, GeminiResponse]:
        # config what gemini should do, generate flashcards, how many, and return as json matching schema
        config = types.GenerateContentConfig(temperature=0.3)
        prompt = (
            "Generate study flashcards from the notes below.\n"
            f"Return exactly {num_cards} items as raw JSON only.\n"
            'Each item must be shaped like {"question": "...", "answer": "..."}.\n'
            "Do not include markdown, comments, or extra text.\n\n"
            f"Notes:\n{notes}"
        )
        # set up http options, including api version and any aiohttp settings
        http_options = types.HttpOptions(
            api_version=self.api_version,
            async_client_args={},
        )   
        # make the async call to Gemini API, handle any errors, and parse the response
        try:
            async with genai.Client(
                api_key=self.api_key,
                http_options=http_options,
            ).aio as aclient:
                # make the API call to generate content with the given notes and config
                response = await aclient.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
        # handle API errors separately to capture status codes, then catch-all for any other exceptions
        except errors.APIError as exc:
            # if it's a rate limit error, we can set a specific status, otherwise it's a general failure
            status_name = (
                "rate_limited"
                if exc.code == status.HTTP_429_TOO_MANY_REQUESTS
                else "failed"
            )
            # returns none for data and a gemini response with error details
            return None, GeminiResponse(
                model_name=self.model,
                status=status_name,
                error_code=exc.code,
                error_message=exc.message,
                raw_response=str(exc.response),
            )
        # catches any other unexpected errors like network timeouts
        except Exception as exc:
            return None, GeminiResponse(
                model_name=self.model,
                status="failed",
                error_code=None,
                error_message="Unknown error occurred while contacting Gemini",
                raw_response=str(exc),
            )
        #gets raw text from gemini's repsonse
        raw_text = response.text
        # checks if gemini returned nothing or just whitespace
        if not raw_text or not raw_text.strip():
            return None, GeminiResponse(
                model_name=self.model,
                status="failed",
                error_code=None,
                error_message="Empty response from Gemini",
                raw_response=raw_text,
            )
        try:
            parsed = _parse_json_array(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            return None, GeminiResponse(
                model_name=self.model,
                status="invalid_json",
                error_code=None,
                error_message=f"Gemini response is not valid JSON: {exc}",
                raw_response=raw_text,
            )
        #validates eahc item in the parsed response against our Flashcard model, if any item fails validation, return an error response with details
        try:
            validated = [Flashcard.model_validate(item) for item in cast(list[object], parsed)]
        except ValidationError as exc:
            return None, GeminiResponse(
                model_name=self.model,
                status="invalid_json",
                error_code=None,
                error_message=f"Schema validation failed: {exc}",
                raw_response=raw_text,
            )   
        
        # if gemini returned the exact number of cards we asked for
        if len(validated) != num_cards:
            return None, GeminiResponse(
                model_name=self.model,
                status="invalid_json",
                error_code=None,
                error_message=f"Expected {num_cards} flashcards, got {len(validated)}",
                raw_response=raw_text,
            )
        #if everything is validated and correct, return the flashcards, with no error messages and success reply
        return validated, GeminiResponse(
            model_name=self.model,
            status="success",
            error_code=None,
            error_message=None,
            raw_response=raw_text,
        )
    
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
            temperature=0.3,
        )
        prompt = (
            "Generate exam-style multiple choice questions from the notes below.\n"
            f"Return exactly {num_questions} items as raw JSON only.\n"
            "Each item must include question, option_a, option_b, option_c, option_d, "
            "correct_answer, and explanation.\n"
            "correct_answer must be one of A, B, C, or D.\n"
            f"Difficulty level: {difficulty}.\n"
            "Do not include markdown, comments, or extra text.\n\n"
            f"Notes:\n{notes}"
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
                    contents=prompt,
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
        
        try:
            parsed = _parse_json_array(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            return None, GeminiResponse(
                model_name=self.model,
                status="invalid_json",
                error_code=None,
                error_message=f"Gemini response is not valid JSON: {exc}",
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
