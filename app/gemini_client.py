import os
import json
import logging
import re
import google.generativeai as genai
from dotenv import load_dotenv
from typing import Type, TypeVar, Optional
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# GEMINI CONFIGURATION
# ---------------------------------------------------------

api_key = os.getenv("GEMINI_API_KEY")

if api_key:
    genai.configure(api_key=api_key)
else:
    logger.warning(
        "GEMINI_API_KEY environment variable is not set. "
        "Gemini API calls will fail."
    )

T = TypeVar("T", bound=BaseModel)


def get_model_name() -> str:
    """
    Gets the Gemini model name from .env.
    """
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def is_gemini_configured() -> bool:
    """
    Checks whether a Gemini API key is configured.
    """
    return bool(os.getenv("GEMINI_API_KEY"))


# ---------------------------------------------------------
# HELPER: CLEAN GEMINI JSON
# ---------------------------------------------------------

def _extract_json(text: str) -> str:
    """
    Extracts JSON from Gemini's response.

    Gemini may sometimes return:
        ```json
        {...}
        ```

    instead of raw JSON.

    This function removes markdown code fences if present.
    """

    text = text.strip()

    # Remove ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Find the first JSON object if Gemini added extra text
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    return text.strip()


# ---------------------------------------------------------
# STRUCTURED OUTPUT
# ---------------------------------------------------------

def generate_structured_output(
    prompt: str,
    response_schema: Type[T],
    system_instruction: Optional[str] = None
) -> T:
    """
    Calls Gemini and converts its JSON response into
    the requested Pydantic model.

    IMPORTANT:
    We intentionally DO NOT pass the Pydantic model as
    response_schema to Gemini.

    The older google-generativeai SDK cannot reliably handle
    Pydantic v2 JSON schemas containing fields such as:

        $defs
        $ref
        anyOf
        default

    Instead, we ask Gemini for JSON and validate it ourselves
    using Pydantic.
    """

    if not is_gemini_configured():
        raise ValueError(
            "Gemini API key is not configured. "
            "Please add GEMINI_API_KEY to your .env file."
        )

    model_name = get_model_name()

    # -----------------------------------------------------
    # Tell Gemini explicitly to return JSON.
    # -----------------------------------------------------

    json_instruction = f"""
IMPORTANT OUTPUT RULES:

Return ONLY valid JSON.

Do NOT use Markdown.
Do NOT use ```json.
Do NOT add explanations before or after the JSON.

The JSON must represent this Pydantic model:

{response_schema.__name__}

The JSON will be validated by the application after Gemini
returns it.

If a field is a list, return a JSON array.
If a field is optional and not needed, return null.
If a field has a default value, you may explicitly provide it.

Make sure ALL required fields are present.
"""

    combined_system_instruction = (
        (system_instruction or "")
        + "\n\n"
        + json_instruction
    )

    # -----------------------------------------------------
    # Create Gemini model
    # -----------------------------------------------------

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=combined_system_instruction
    )

    try:

        # -------------------------------------------------
        # Ask Gemini for JSON WITHOUT response_schema.
        # -------------------------------------------------

        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0
            )
        )

        if not response or not response.text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        raw_text = response.text.strip()

        logger.debug(
            "Raw Gemini structured response: %s",
            raw_text
        )

        # -------------------------------------------------
        # Clean possible Markdown/code fences
        # -------------------------------------------------

        json_text = _extract_json(raw_text)

        # -------------------------------------------------
        # Parse JSON
        # -------------------------------------------------

        try:
            data = json.loads(json_text)

        except json.JSONDecodeError as json_error:
            logger.error(
                "Gemini returned invalid JSON: %s",
                raw_text
            )

            raise RuntimeError(
                f"Gemini returned invalid JSON: {json_error}"
            )

        # -------------------------------------------------
        # Validate using Pydantic
        # -------------------------------------------------

        try:
            return response_schema.model_validate(data)

        except Exception as validation_error:

            logger.error(
                "Gemini JSON failed Pydantic validation: %s",
                validation_error
            )

            logger.error(
                "Gemini JSON received: %s",
                data
            )

            raise RuntimeError(
                "Gemini returned JSON that does not match "
                f"{response_schema.__name__}: "
                f"{validation_error}"
            )

    except Exception as e:

        logger.error(
            "Gemini Structured Call failed: %s",
            str(e)
        )

        # Don't double-wrap our own RuntimeErrors
        if isinstance(e, RuntimeError):
            raise

        raise RuntimeError(
            f"Error communicating with Gemini: {e}"
        )


# ---------------------------------------------------------
# NORMAL TEXT RESPONSE
# ---------------------------------------------------------

def generate_text_response(
    prompt: str,
    system_instruction: Optional[str] = None
) -> str:
    """
    Calls Gemini and returns a normal text response.
    """

    if not is_gemini_configured():
        raise ValueError(
            "Gemini API key is not configured. "
            "Please add GEMINI_API_KEY to your .env file."
        )

    model_name = get_model_name()

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_instruction
    )

    try:

        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2
            )
        )

        if not response or not response.text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        return response.text.strip()

    except Exception as e:

        logger.error(
            "Gemini Plain text call failed: %s",
            str(e)
        )

        raise RuntimeError(
            f"Error communicating with Gemini: {e}"
        )