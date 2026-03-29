import copy
import json
import logging
import re

try:
    from google import genai as _google_genai
except Exception:
    try:
        import google.genai as _google_genai
    except Exception:
        _google_genai = None

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

DEFAULT_BRAND_RULES = [
    "Use professional tone",
    "Avoid exaggerated claims",
    "No slang",
    "Use approved terminology only",
]

_SLANG_TERMS = {
    "awesome",
    "crazy",
    "super",
    "lit",
    "cool",
    "gonna",
    "wanna",
}
_EXAGGERATED_PATTERNS = [
    r"\b(best|greatest|ultimate)\b",
    r"\bguaranteed\b",
    r"\b100%\b",
    r"\bno\.?1\b",
]

_gemini_client = None
if GEMINI_API_KEY:
    try:
        if _google_genai is None:
            raise RuntimeError("google-genai package is unavailable")
        _gemini_client = _google_genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        logger.warning("Gemini init failed in brand governance: %s", exc)


def _scan_text(field_name: str, text: str):
    violations = []
    value = str(text or "")
    lower = value.lower()

    for slang in _SLANG_TERMS:
        if re.search(rf"\b{re.escape(slang)}\b", lower):
            violations.append(f"{field_name}: contains slang term '{slang}'")

    for pattern in _EXAGGERATED_PATTERNS:
        if re.search(pattern, lower):
            violations.append(f"{field_name}: contains exaggerated claim pattern '{pattern}'")

    if lower.count("!") > 2:
        violations.append(f"{field_name}: too many exclamation marks for professional tone")

    return violations


def _extract_text_fields(content: dict):
    fields = {}
    for key in ["idea", "hook", "script", "caption"]:
        fields[key] = str(content.get(key, "") or "")
    return fields


def _sanitize_without_llm(content: dict):
    corrected = copy.deepcopy(content)
    for key in ["idea", "hook", "script", "caption"]:
        text = str(corrected.get(key, "") or "")
        text = re.sub(r"(?i)\b(awesome|crazy|lit|gonna|wanna)\b", "", text)
        text = re.sub(r"(?i)\b(best|greatest|ultimate)\b", "strong", text)
        text = re.sub(r"(?i)\b100%\b", "high", text)
        text = re.sub(r"!{2,}", "!", text)
        corrected[key] = " ".join(text.split()).strip()
    return corrected


def _auto_correct_with_gemini(content: dict, brand_rules: list):
    if not _gemini_client:
        return None
    prompt = (
        "Rewrite the JSON text fields to follow the brand governance rules.\n"
        f"Rules: {json.dumps(brand_rules)}\n"
        "Keep meaning, keep structure, and keep non-text fields unchanged.\n"
        "Only rewrite: idea, hook, script, caption.\n"
        "Return only valid JSON with keys: idea, hook, script, caption.\n\n"
        f"{json.dumps(_extract_text_fields(content), ensure_ascii=False)}"
    )
    try:
        resp = _gemini_client.models.generate_content(
            model=(GEMINI_MODEL or "gemini-2.5-flash"),
            contents=prompt,
        )
        text = getattr(resp, "text", "") or ""
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception as exc:
        logger.warning("Brand auto-correct via Gemini failed: %s", exc)
        return None


def enforce_brand_rules(content, brand_rules=None):
    """
    Validates and corrects content based on brand guidelines.
    """
    if not isinstance(content, dict):
        content = {}
    rules = brand_rules or DEFAULT_BRAND_RULES
    fields = _extract_text_fields(content)
    violations = []
    for field_name, value in fields.items():
        violations.extend(_scan_text(field_name, value))

    corrected_content = copy.deepcopy(content)
    corrected = False
    if violations:
        llm_fix = _auto_correct_with_gemini(content, rules)
        if llm_fix:
            for k in ["idea", "hook", "script", "caption"]:
                if k in llm_fix:
                    corrected_content[k] = llm_fix[k]
            corrected = True
        else:
            corrected_content = _sanitize_without_llm(content)
            corrected = True

    summary = "Brand-safe content" if not violations else "Corrections applied for brand governance."
    return {
        "content": corrected_content,
        "violations": violations,
        "corrected": corrected,
        "rules_applied": rules,
        "summary": summary,
    }
