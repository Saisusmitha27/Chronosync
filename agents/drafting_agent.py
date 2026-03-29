import json
import logging
import re
import time
from urllib.parse import quote_plus

import requests
try:
    from google import genai as _google_genai
except Exception:
    try:
        import google.genai as _google_genai
    except Exception:
        _google_genai = None

from utils.trend_fetcher import get_trends
from utils.emotion_analyzer import analyze_emotion
from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    PEXELS_API_KEY,
    PIXABAY_API_KEY,
    DEFAULT_FALLBACK_VIDEO,
)

logger = logging.getLogger(__name__)

SAFE_FALLBACK_VISUALS = [
    "business office",
    "team working",
    "person using laptop",
]

ABSTRACT_TERMS = {
    "growth",
    "success",
    "solution",
    "innovation",
    "strategy",
    "optimization",
    "efficiency",
    "performance",
    "scalability",
    "transformation",
    "impact",
    "results",
    "progress",
    "vision",
    "value",
    "synergy",
    "leadership",
}

CONCRETE_HINTS = {
    "person",
    "people",
    "team",
    "office",
    "laptop",
    "computer",
    "meeting",
    "desk",
    "keyboard",
    "phone",
    "employee",
    "worker",
    "engineer",
    "developer",
    "hands",
    "city",
    "street",
    "factory",
    "warehouse",
    "workspace",
    "collaboration",
    "conference",
    "store",
    "retail",
    "customer",
}

MIN_SCENES = 6
MAX_SCENES = 8
DEFAULT_SCENE_DURATION = 5
MIN_WORDS = 80
MAX_WORDS = 110
_GEMINI_RETRY_DELAY_DEFAULT = 10.0

_gemini_client = None
if GEMINI_API_KEY:
    try:
        if _google_genai is None:
            raise RuntimeError("google-genai package is not available")
        _gemini_client = _google_genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        logger.warning("Gemini SDK init failed: %s", exc)


def _extract_balanced_json(text: str):
    start = text.find("{")
    if start == -1:
        return None
    in_str = False
    escape = False
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def parse_json_safe(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        extracted = _extract_balanced_json(text)
        if extracted:
            text = extracted
        return json.loads(text)
    except Exception as exc:
        logger.error("JSON parse failed: %s | Raw: %.500s", exc, raw)
        return {}


def _normalize_visual(visual_text: str) -> str:
    if not isinstance(visual_text, str):
        return SAFE_FALLBACK_VISUALS[0]
    visual = " ".join(visual_text.strip().split())
    if not visual:
        return SAFE_FALLBACK_VISUALS[0]
    lower = visual.lower()
    has_concrete = any(h in lower for h in CONCRETE_HINTS)
    has_abstract = any(t in lower for t in ABSTRACT_TERMS)
    if has_abstract and not has_concrete:
        return SAFE_FALLBACK_VISUALS[0]
    if len(visual.split()) < 2:
        return SAFE_FALLBACK_VISUALS[0]
    return visual


def _normalize_text_overlay(text: str, narration: str = "") -> str:
    candidate = text or narration or "Watch this"
    words = str(candidate).split()
    return " ".join(words[:6]) if words else "Watch this"


def validate_scene(scene: dict) -> dict:
    if not isinstance(scene, dict):
        scene = {}
    scene["visual"] = _normalize_visual(scene.get("visual") or scene.get("narration") or "")
    scene["text_overlay"] = _normalize_text_overlay(scene.get("text_overlay"), scene.get("narration", ""))
    scene["narration"] = str(scene.get("narration") or "").strip() or "Continue the story."
    return scene


def _enforce_script_length(script: str) -> str:
    words = str(script or "").split()
    if not words:
        script = (
            "This video explains the topic clearly, shows practical examples, and gives viewers a simple action "
            "they can take today to get better results."
        )
        words = script.split()
    if len(words) < MIN_WORDS:
        filler = (
            " It also highlights real world use cases, common mistakes to avoid, measurable outcomes, and "
            "step by step guidance for viewers."
        )
        while len(words) < MIN_WORDS:
            script += filler
            words = script.split()
    if len(words) > MAX_WORDS:
        script = " ".join(words[:MAX_WORDS])
    if script and script[-1] not in ".!?":
        script += "."
    lower_script = script.lower()
    if not any(k in lower_script for k in ["in conclusion", "finally", "to sum up", "take action", "start today"]):
        script += " In conclusion, take one action today and stay consistent."
    return script


def _enforce_scenes(content: dict):
    scenes = content.get("scenes")
    if not isinstance(scenes, list):
        scenes = []
    scenes = [validate_scene(s) for s in scenes if isinstance(s, dict)]

    if not scenes:
        scenes = [
            {"scene": 1, "narration": "Open with the key problem.", "visual": "person thinking at desk", "text_overlay": "The challenge"},
            {"scene": 2, "narration": "Show why this matters now.", "visual": "busy office team", "text_overlay": "Why now"},
            {"scene": 3, "narration": "Introduce the core approach.", "visual": "team planning on whiteboard", "text_overlay": "Core idea"},
            {"scene": 4, "narration": "Present a practical example.", "visual": "person using laptop", "text_overlay": "Example"},
            {"scene": 5, "narration": "Highlight measurable benefit.", "visual": "business dashboard on screen", "text_overlay": "Impact"},
            {"scene": 6, "narration": "Address common mistakes.", "visual": "person reviewing checklist", "text_overlay": "Avoid mistakes"},
            {"scene": 7, "narration": "Share a quick next step.", "visual": "hands writing action plan", "text_overlay": "Next step"},
            {"scene": 8, "narration": "Close with a clear CTA.", "visual": "person speaking to camera", "text_overlay": "Take action"},
        ]

    if len(scenes) < MIN_SCENES:
        idx = 0
        while len(scenes) < MIN_SCENES:
            base = dict(scenes[idx % len(scenes)])
            base["scene"] = len(scenes) + 1
            scenes.append(validate_scene(base))
            idx += 1
    if len(scenes) > MAX_SCENES:
        scenes = scenes[:MAX_SCENES]

    for i, scene in enumerate(scenes):
        scene["scene"] = i + 1
        duration = scene.get("duration", DEFAULT_SCENE_DURATION)
        try:
            duration = float(duration)
        except Exception:
            duration = DEFAULT_SCENE_DURATION
        scene["duration"] = max(4.0, min(6.0, duration))

    content["scenes"] = scenes
    return content


def build_search_query(visual: str, niche: str) -> str:
    visual = str(visual or "").strip()
    niche = str(niche or "").strip()
    if not niche or niche.lower() in visual.lower():
        return visual
    return f"{niche} {visual}".strip()


def _sanitize_media_query(query: str, max_words: int = 8, max_chars: int = 80) -> str:
    """
    Convert verbose scene text into a stock-search friendly keyword phrase.
    Keeps only alnum/space tokens, trims stopwords, enforces short length.
    """
    raw = str(query or "").lower().strip()
    if not raw:
        return "business office"

    cleaned = re.sub(r"[^a-z0-9\s]", " ", raw)
    tokens = [t for t in cleaned.split() if t]
    stop = {
        "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "at",
        "is", "are", "be", "this", "that", "various", "brightly", "lit",
    }
    filtered = [t for t in tokens if t not in stop]
    if not filtered:
        filtered = tokens[:]
    short = " ".join(filtered[:max_words]).strip()
    if len(short) > max_chars:
        short = short[:max_chars].rsplit(" ", 1)[0].strip()
    return short or "business office"


def fetch_pexels_video(query: str) -> str:
    search_query = _sanitize_media_query(query, max_words=10, max_chars=90)
    if not search_query or not PEXELS_API_KEY:
        return ""
    logger.info("[PEXELS] Query: %s", search_query)
    try:
        resp = requests.get(
            f"https://api.pexels.com/videos/search?query={quote_plus(search_query)}&per_page=10",
            headers={"Authorization": PEXELS_API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        candidates = []
        for video in resp.json().get("videos") or []:
            for file_info in video.get("video_files", []):
                if file_info.get("file_type") != "video/mp4":
                    continue
                link = file_info.get("link", "")
                if not link or ".mp4" not in link:
                    continue
                quality = (file_info.get("quality") or "").lower()
                score = (2 if quality == "hd" else 0, file_info.get("height", 0), file_info.get("width", 0))
                candidates.append((score, link))
        if not candidates:
            logger.info("[PEXELS] No MP4 candidates for query: %s", search_query)
            return ""
        candidates.sort(key=lambda x: x[0], reverse=True)
        selected = candidates[0][1]
        logger.info("[PEXELS] Selected URL: %s", selected)
        return selected
    except Exception as exc:
        logger.warning("Pexels lookup failed for '%s': %s", query, exc)
        return ""


def fetch_pixabay_video(query: str) -> str:
    search_query = _sanitize_media_query(query, max_words=6, max_chars=60)
    if not search_query or not PIXABAY_API_KEY:
        return ""
    logger.info("[PIXABAY] Query: %s", search_query)
    try:
        resp = requests.get(
            f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={quote_plus(search_query)}&per_page=3",
            timeout=20,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits") or []
        if not hits:
            logger.info("[PIXABAY] No hits for query: %s", search_query)
            return ""
        selected = hits[0].get("videos", {}).get("medium", {}).get("url", "")
        if selected:
            logger.info("[PIXABAY] Selected URL: %s", selected)
        return selected
    except Exception as exc:
        logger.warning("Pixabay lookup failed for '%s': %s", query, exc)
        return ""


def get_stock_video_sources(query: str) -> dict:
    primary = fetch_pexels_video(query)
    if primary:
        return {"primary": primary, "fallback": fetch_pixabay_video(query) or DEFAULT_FALLBACK_VIDEO}
    primary = fetch_pixabay_video(query)
    if primary:
        return {"primary": primary, "fallback": DEFAULT_FALLBACK_VIDEO}
    return {"primary": DEFAULT_FALLBACK_VIDEO, "fallback": DEFAULT_FALLBACK_VIDEO}


def generate_prompt(
    topic,
    audience,
    location,
    platform,
    tone,
    trend,
    emotion,
    internal_data="",
    content_strategy=None,
    regenerate_instruction="",
):
    strategy = content_strategy or {}
    strategy_lines = []
    if strategy.get("hook_style"):
        strategy_lines.append(f"- Hook style: {strategy.get('hook_style')}")
    if strategy.get("scene_duration"):
        strategy_lines.append(f"- Scene duration preference: {strategy.get('scene_duration')}")
    if strategy.get("caption_style"):
        strategy_lines.append(f"- Caption style: {strategy.get('caption_style')}")
    if strategy.get("notes"):
        notes = strategy.get("notes")
        if isinstance(notes, list):
            strategy_lines.extend([f"- {n}" for n in notes[:3]])
        else:
            strategy_lines.append(f"- Notes: {notes}")
    strategy_block = "\n".join(strategy_lines) if strategy_lines else "- Keep balanced storytelling."
    knowledge_block = (str(internal_data or "").strip())[:3500]
    if not knowledge_block:
        knowledge_block = "No internal enterprise document provided."
    regen_line = regenerate_instruction.strip() or "None"
    return f"""
You are an expert short-form video content strategist.
Return ONLY valid JSON and nothing else.

Topic: {topic}
Audience: {audience}
Location: {location}
Platform: {platform}
Tone: {tone}
Trend context: {trend}
Emotion context: {emotion}
Regeneration instruction: {regen_line}

Content optimization strategy:
{strategy_block}

Internal enterprise knowledge/context:
{knowledge_block}

Strict requirements:
- Script must be 80 to 110 words (targeting 30-35 seconds).
- Create 6 to 8 scenes.
- Each scene must include narration, visual, text_overlay, and duration.
- Each scene duration must be between 4 and 6 seconds.
- Visual must be concrete, searchable, and directly related to the topic/product.
- text_overlay max 6 words.
- Avoid abstract visual terms.
- The final scene must clearly conclude the message with a CTA/conclusion line.
- Avoid unrelated generic office visuals unless the topic is business productivity.

Output schema:
{{
  "idea":"...",
  "hook":"...",
  "script":"...",
  "caption":"...",
  "hashtags":["...","..."],
  "seo_keywords":["...","..."],
  "scenes":[
    {{
      "scene":1,
      "narration":"...",
      "visual":"...",
      "text_overlay":"...",
      "duration":5
    }}
  ]
}}
"""


def call_gemini(prompt: str) -> str:
    if not _gemini_client or not GEMINI_API_KEY:
        raise RuntimeError("Gemini SDK not initialized. Check GEMINI_API_KEY.")
    model_name = GEMINI_MODEL or "gemini-2.5-flash"
    errors = []
    for attempt in range(2):
        try:
            response = _gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = getattr(response, "text", "") or ""
            if not text:
                raise RuntimeError("Gemini returned empty response text.")
            return text
        except Exception as exc:
            msg = str(exc)
            errors.append(f"{model_name}: {msg}")
            is_quota = "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
            if is_quota and attempt == 0:
                delay = _GEMINI_RETRY_DELAY_DEFAULT
                m = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
                if m:
                    delay = float(m.group(1))
                m2 = re.search(r"'retryDelay':\s*'([0-9]+)s'", msg)
                if m2:
                    delay = float(m2.group(1))
                delay = max(1.0, min(delay, 20.0))
                logger.warning("Gemini quota hit on %s; retrying in %.1fs", model_name, delay)
                time.sleep(delay)
                continue
            break

    raise RuntimeError("Gemini generation failed: " + " | ".join(errors[-2:]))


def call_groq(prompt: str) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not configured.")
    models_to_try = []
    for candidate in [GROQ_MODEL, "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        if candidate and candidate not in models_to_try:
            models_to_try.append(candidate)

    errors = []
    for model_name in models_to_try:
        for json_mode in (True, False):
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "Return valid JSON only. No markdown."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not text:
                    raise RuntimeError("Groq returned empty response content.")
                return text
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                body = exc.response.text if exc.response is not None else str(exc)
                errors.append(f"{model_name} ({status}): {body[:220]}")
                lower = body.lower()
                if status == 400 and json_mode and ("response_format" in lower or "json_object" in lower):
                    logger.warning("Groq model %s rejected json_object format; retrying without response_format.", model_name)
                    continue
                if status == 400 and ("decommissioned" in lower or "no longer supported" in lower):
                    logger.warning("Groq model %s is unavailable; trying next model.", model_name)
                    break
                if status in (401, 403):
                    raise RuntimeError(f"Groq authentication/permission failed ({status}).")
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")
                if json_mode:
                    continue
                break
    raise RuntimeError("Groq generation failed: " + " | ".join(errors[-4:]))


def call_llm(prompt: str):
    errors = []
    if GEMINI_API_KEY:
        try:
            return call_gemini(prompt), "gemini"
        except Exception as exc:
            errors.append(str(exc))
            logger.warning("Gemini failed, trying Groq fallback: %s", exc)
    if GROQ_API_KEY:
        try:
            return call_groq(prompt), "groq"
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("All LLM providers failed: " + " | ".join(errors))


def _build_fallback_content(topic: str, audience: str, platform: str, reason: str, raw: str):
    content = {
        "idea": f"{topic} insights for {audience}",
        "hook": f"How {topic} is changing outcomes",
        "script": _enforce_script_length(
            f"{topic} is becoming more important every day. This video explains practical steps, examples, "
            f"common mistakes, and a clear call to action for {audience} on {platform}."
        ),
        "caption": f"Practical {topic} guide for {audience}.",
        "hashtags": ["#AI", "#Content", "#Automation", "#Marketing", "#Shorts", "#Reels", "#Growth", "#Digital", "#Strategy", "#Creator"],
        "seo_keywords": [topic, audience, platform, "short video", "content strategy"],
        "scenes": [],
        "_fallback": True,
        "_fallback_reason": reason,
        "_fallback_raw": (raw or "")[:1000],
    }
    return _enforce_scenes(content)


def draft_content(
    niche: str,
    audience: str,
    location: str,
    platform: str,
    tone: str,
    internal_data: str = "",
    content_strategy: dict | None = None,
    regenerate_instruction: str = "",
):
    trends = []
    top_trend = niche
    emotion = "neutral"
    parsed = {}
    last_raw = ""
    error_reason = ""
    provider = ""

    try:
        trends = get_trends(location, niche)
        top_trend = trends[0] if trends else niche
        emotion = analyze_emotion(top_trend)
        prompt = generate_prompt(
            niche,
            audience,
            location,
            platform,
            tone,
            top_trend,
            emotion,
            internal_data=internal_data,
            content_strategy=content_strategy,
            regenerate_instruction=regenerate_instruction,
        )
        raw_output, provider = call_llm(prompt)
        last_raw = raw_output
        parsed = parse_json_safe(raw_output)
        if not parsed and provider == "gemini" and GROQ_API_KEY:
            raw_output = call_groq(prompt)
            last_raw = raw_output
            provider = "groq"
            parsed = parse_json_safe(raw_output)
    except Exception as exc:
        error_reason = str(exc)
        logger.warning("Draft pipeline failed: %s", exc)

    if not parsed:
        parsed = _build_fallback_content(niche, audience, platform, error_reason or "Failed to parse model output", last_raw)
        provider = provider or "fallback"
    if isinstance(parsed, dict) and parsed.get("_fallback"):
        parsed["_fallback_provider"] = provider or "fallback"

    parsed["script"] = _enforce_script_length(parsed.get("script", ""))
    parsed = _enforce_scenes(parsed)
    parsed["_llm_provider"] = provider

    scenes = parsed.get("scenes", [])
    for i, scene in enumerate(scenes):
        scene = validate_scene(scene)
        scene["scene"] = i + 1
        query = build_search_query(scene.get("visual", ""), niche)
        if not scene.get("media_url") and not scene.get("media_path"):
            sources = get_stock_video_sources(query)
            scene["media_url"] = sources.get("primary")
            scene["media_fallback_url"] = sources.get("fallback")
            scene["media_query"] = query

    return {
        "trends": trends,
        "top_trend": top_trend,
        "emotion": emotion,
        "strategy_used": content_strategy or {},
        "content": parsed,
    }
