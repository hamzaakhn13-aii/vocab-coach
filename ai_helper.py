"""
ai_helper.py
All the Gemini (AI) logic lives here, so app.py only has to deal with the screen.
"""

import json
import re

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-3.5-flash"
LEVELS = ["Beginner", "Intermediate", "Advanced"]
MAX_WORDS = 15


class AIError(Exception):
    """A friendly error message that is safe to show to the user."""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def parse_words(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """Turn 'helo, wrld\\nbeutiful' into ['helo', 'wrld', 'beutiful'] (no duplicates)."""
    parts = re.split(r"[,\n;]+", text or "")
    words, seen = [], set()
    for part in parts:
        word = part.strip().strip("\"'.!?")
        if not word:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(word[:60])  # no crazy long input
    return words[:max_words]


def _extract_json(text: str):
    """Read JSON from the model reply, even if it added ```json fences."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    raise AIError("The AI sent a reply I could not read. Please try again.")


def _ask_gemini(api_key: str, model: str, prompt: str):
    if not api_key:
        raise AIError("Please add your Gemini API key first.")
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model or DEFAULT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
    except Exception as exc:  # network, bad key, wrong model name, quota...
        message = str(exc)
        lowered = message.lower()
        if "api key" in lowered or "api_key" in lowered or "401" in lowered or "403" in lowered:
            raise AIError("Your API key looks wrong or has no permission. Please check it.") from exc
        if "404" in lowered or "not found" in lowered:
            raise AIError(
                f"The model '{model}' was not found. Try 'gemini-2.5-flash' in the sidebar."
            ) from exc
        if "429" in lowered or "quota" in lowered or "resource_exhausted" in lowered:
            raise AIError("Too many requests or free limit reached. Wait a minute and try again.") from exc
        raise AIError(f"Could not reach Gemini: {message[:200]}") from exc

    return _extract_json(getattr(response, "text", ""))


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


# --------------------------------------------------------------------------
# 1) Spelling correction + vocabulary help
# --------------------------------------------------------------------------
def analyze_words(api_key: str, model: str, words: list[str], level: str = "Intermediate") -> list[dict]:
    if not words:
        raise AIError("Please type at least one word.")

    prompt = f"""You are a friendly English spelling and vocabulary teacher.
The learner's level is: {level}.

Below is a JSON list of words typed by the learner. Some may be spelled wrongly.
For EVERY word, in the SAME order, return one object with these keys:
- "original": the word exactly as typed
- "corrected": the correct English spelling (same as original if already correct;
  empty string "" if you really cannot guess the word)
- "is_correct": true if the original was already spelled correctly, otherwise false
- "part_of_speech": e.g. noun, verb, adjective
- "meaning": a simple meaning, suitable for a {level} learner
- "example": one example sentence using the corrected word
- "synonyms": list of up to 3 similar words
- "better_words": list of up to 3 stronger or more precise words a learner can use
  to sound more natural or advanced (empty list if none)
- "tip": one short tip to remember the spelling or avoid a common mistake

Return ONLY a JSON array, nothing else.

Words: {json.dumps(words)}"""

    data = _ask_gemini(api_key, model, prompt)
    if isinstance(data, dict):  # sometimes the list is wrapped in an object
        data = next((v for v in data.values() if isinstance(v, list)), [data])
    if not isinstance(data, list):
        raise AIError("The AI reply was not in the expected format. Please try again.")

    results = []
    for index, word in enumerate(words):
        item = data[index] if index < len(data) and isinstance(data[index], dict) else {}
        corrected = str(item.get("corrected", "")).strip()
        results.append(
            {
                "original": word,
                "corrected": corrected,
                "is_correct": bool(item.get("is_correct", corrected.lower() == word.lower())),
                "part_of_speech": str(item.get("part_of_speech", "")).strip(),
                "meaning": str(item.get("meaning", "")).strip(),
                "example": str(item.get("example", "")).strip(),
                "synonyms": _as_list(item.get("synonyms")),
                "better_words": _as_list(item.get("better_words")),
                "tip": str(item.get("tip", "")).strip(),
            }
        )
    return results


# --------------------------------------------------------------------------
# 2) Quiz
# --------------------------------------------------------------------------
def make_quiz(api_key: str, model: str, words: list[str], level: str = "Intermediate") -> list[dict]:
    if len(words) < 1:
        raise AIError("Check some words first, then I can make a quiz from them.")

    count = min(5, max(3, len(words)))
    prompt = f"""You are an English vocabulary teacher. Learner level: {level}.
Create {count} multiple-choice questions that test the meaning or correct use of
these words: {json.dumps(words)}.
Use a different word for each question when possible.

Return ONLY a JSON array. Each item must have:
- "question": the question text
- "options": exactly 4 short answer options
- "answer_index": the number (0 to 3) of the correct option
- "explanation": one short sentence explaining the answer
"""
    data = _ask_gemini(api_key, model, prompt)
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    if not isinstance(data, list):
        raise AIError("The AI reply was not in the expected format. Please try again.")

    quiz = []
    for item in data:
        if not isinstance(item, dict):
            continue
        options = _as_list(item.get("options"))
        try:
            answer = int(item.get("answer_index"))
        except (TypeError, ValueError):
            continue
        if len(options) != 4 or not 0 <= answer <= 3 or not str(item.get("question", "")).strip():
            continue
        quiz.append(
            {
                "question": str(item["question"]).strip(),
                "options": options,
                "answer_index": answer,
                "explanation": str(item.get("explanation", "")).strip(),
            }
        )
    if not quiz:
        raise AIError("I could not build a quiz this time. Please try again.")
    return quiz
