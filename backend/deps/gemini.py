import os
from typing import cast

from fastapi import HTTPException, status
from google import genai
from google.genai import errors, types
from pydantic import BaseModel


class Flashcard(BaseModel):
    """Model for a flashcard with a question and answer."""

    question: str
    answer: str


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
    ) -> list[dict[str, str]]:
        """Generates flashcards from notes using Gemini API."""
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
        return [card.model_dump() for card in parsed_cards]


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
