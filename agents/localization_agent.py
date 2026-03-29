import json
import logging

try:
    from google import genai as _google_genai
except Exception:
    try:
        import google.genai as _google_genai
    except Exception:
        _google_genai = None

from utils.translation_helper import translate_text
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

LOCATION_LANGUAGE = {
    "chennai": "tamil",
    "madurai": "tamil",
    "coimbatore": "tamil",
    "hyderabad": "telugu",
    "visakhapatnam": "telugu",
    "bengaluru": "kannada",
    "mysore": "kannada",
    "kochi": "malayalam",
    "thiruvananthapuram": "malayalam",
    "kolkata": "bengali",
    "mumbai": "marathi",
    "bhubaneswar": "odia",
}

SKIP_TRANSLATION_KEYS = {"visual", "media_url", "media_fallback_url", "media_query"}

_gemini_client = None
if GEMINI_API_KEY:
    try:
        if _google_genai is None:
            raise RuntimeError("google-genai package is not available")
        _gemini_client = _google_genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        logger.warning("Gemini init for localization failed: %s", exc)


def map_location_to_language(location: str):
    if not location:
        return "english"
    return LOCATION_LANGUAGE.get(location.strip().lower(), "english")


def _localize_recursive(obj, target_lang: str, key_name: str = ""):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in SKIP_TRANSLATION_KEYS:
                out[k] = v
            else:
                out[k] = _localize_recursive(v, target_lang, k)
        return out
    if isinstance(obj, list):
        return [_localize_recursive(item, target_lang, key_name) for item in obj]
    if isinstance(obj, str):
        if key_name in SKIP_TRANSLATION_KEYS:
            return obj
        return translate_text(obj, target_lang)
    return obj


def _parse_json(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        return None


def localize_with_gemini(content: dict, language: str):
    if not _gemini_client:
        return None
    try:
        prompt = (
            "Translate and localize the JSON below into "
            f"{language}. Keep keys unchanged. Keep URLs unchanged. "
            "Return only valid JSON.\n\n"
            + json.dumps(content, ensure_ascii=False)
        )
        response = _gemini_client.models.generate_content(
            model=(GEMINI_MODEL or "gemini-2.5-flash"),
            contents=prompt,
        )
        text = getattr(response, "text", "") or ""
        parsed = _parse_json(text)
        return parsed
    except Exception as exc:
        logger.warning("Gemini localization failed: %s", exc)
        return None


def localize_content(
    final_content: dict,
    target_locations: list,
    forced_language: str = "Auto",
    use_gemini: bool = False,
):
    localized = []
    for loc in target_locations:
        lang = forced_language.lower() if forced_language and forced_language.lower() != "auto" else map_location_to_language(loc)
        if lang == "english":
            localized_content = final_content
        else:
            localized_content = None
            if use_gemini:
                localized_content = localize_with_gemini(final_content, lang)
            if not isinstance(localized_content, dict):
                localized_content = _localize_recursive(final_content, lang)
        localized.append({"location": loc, "language": lang, "content": localized_content})
    return localized
