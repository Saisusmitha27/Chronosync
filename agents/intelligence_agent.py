import json
import logging
import os

import pandas as pd
import requests
try:
    from google import genai as _google_genai
except Exception:
    try:
        import google.genai as _google_genai
    except Exception:
        _google_genai = None

from utils.supabase_client import supabase
from config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)
_STRATEGY_STORE = {}

_gemini_client = None
if GEMINI_API_KEY:
    try:
        if _google_genai is None:
            raise RuntimeError("google-genai package is not available")
        _gemini_client = _google_genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        logger.warning("Gemini SDK init failed in intelligence agent: %s", exc)


def query_engagement(run_id):
    if not run_id or str(run_id).lower() == "none":
        return []
    try:
        response = supabase.table("engagement").select("*").eq("run_id", run_id).execute()
        return response.data
    except Exception as exc:
        logger.error("Supabase query engagement failed: %s", exc)
        return []


def query_recent_engagement(limit=200):
    try:
        response = supabase.table("engagement").select("*").order("published_at", desc=True).limit(limit).execute()
        return response.data if hasattr(response, "data") and isinstance(response.data, list) else []
    except Exception as exc:
        logger.error("Supabase recent engagement query failed: %s", exc)
        return []


def compute_patterns(engagement_data):
    if not engagement_data:
        return {}
    df = pd.DataFrame(engagement_data)
    if df.empty:
        return {}
    df["published_at"] = pd.to_datetime(df["published_at"])
    df["hour"] = df["published_at"].dt.hour
    return {
        "best_hour": int(df.groupby("hour")["likes"].sum().idxmax()),
        "top_channel": df.groupby("channel")["likes"].sum().idxmax(),
        "avg_likes": float(df["likes"].mean()),
    }


def aggregate_engagement_metrics(engagement_data):
    if not engagement_data:
        return {"views": 0, "likes": 0, "comments": 0, "ctr": 0.0, "watch_time": 0.0}
    total_views = 0.0
    total_likes = 0.0
    total_comments = 0.0
    total_clicks = 0.0
    total_impressions = 0.0
    watch_time_vals = []
    for row in engagement_data:
        if not isinstance(row, dict):
            continue
        total_views += float(row.get("views", 0) or 0)
        total_likes += float(row.get("likes", 0) or 0)
        total_comments += float(row.get("comments", 0) or 0)
        total_clicks += float(row.get("clicks", row.get("link_clicks", 0)) or 0)
        total_impressions += float(row.get("impressions", 0) or 0)
        if row.get("watch_time") is not None:
            watch_time_vals.append(float(row.get("watch_time") or 0))
    ctr = (total_clicks / total_impressions) if total_impressions > 0 else 0.0
    avg_watch_time = (sum(watch_time_vals) / len(watch_time_vals)) if watch_time_vals else 0.0
    return {
        "views": int(total_views),
        "likes": int(total_likes),
        "comments": int(total_comments),
        "ctr": float(ctr),
        "watch_time": float(avg_watch_time),
    }


def optimize_content_strategy(metrics):
    """
    Adjusts future content generation strategy dynamically.
    """
    metrics = metrics or {}
    strategy = {
        "hook_style": "balanced",
        "scene_duration": "standard",
        "caption_style": "clear",
        "notes": [],
    }
    likes = float(metrics.get("likes", 0) or 0)
    views = float(metrics.get("views", 0) or 0)
    engagement = (likes / views) if views > 0 else 0.0
    watch_time = float(metrics.get("watch_time", 0) or 0)
    ctr = float(metrics.get("ctr", 0) or 0)

    if engagement < 0.03:
        strategy["hook_style"] = "stronger"
        strategy["notes"].append("Low engagement detected; use stronger opening hooks.")

    if watch_time < 12:
        strategy["scene_duration"] = "shorter"
        strategy["notes"].append("Low watch time; tighten scene pacing.")

    if ctr < 0.015:
        strategy["caption_style"] = "more engaging"
        strategy["notes"].append("Low CTR; make caption more action-oriented.")

    if not strategy["notes"]:
        strategy["notes"].append("Stable engagement; keep current strategy baseline.")
    return strategy


def load_project_strategy(project_key: str):
    return _STRATEGY_STORE.get(project_key)


def store_project_strategy(project_key: str, strategy: dict):
    if not project_key:
        return
    _STRATEGY_STORE[project_key] = strategy or {}


def derive_project_strategy(project_key: str, engagement_data: list):
    metrics = aggregate_engagement_metrics(engagement_data)
    strategy = optimize_content_strategy(metrics)
    store_project_strategy(project_key, strategy)
    return strategy


def _fallback_strategy():
    return {
        "strategy": json.dumps(
            {
                "post_timings": "Post between 7-9 AM and 6-9 PM local time",
                "formats": "Short-form video with subtitles and carousel support",
                "tone": "Conversational and useful",
                "notes": "Fallback strategy",
            }
        )
    }


def _build_prompt(patterns, run_data):
    return (
        "Return only valid JSON.\n"
        "Given engagement patterns and run data, generate optimization strategy.\n"
        f"Patterns: {json.dumps(patterns, default=str)}\n"
        f"Run data: {json.dumps(run_data, default=str)[:900]}\n"
        'Schema: {"post_timings":"...","formats":"...","tone":"...","notes":"..."}'
    )


def call_gemini_for_strategy(patterns, run_data):
    if not _gemini_client:
        return {"error": "Gemini unavailable"}
    prompt = _build_prompt(patterns, run_data)
    try:
        response = _gemini_client.models.generate_content(
            model=(GEMINI_MODEL or "gemini-2.5-flash"),
            contents=prompt,
        )
        text = getattr(response, "text", "") or ""
        if not text:
            return {"error": "Gemini empty response"}
        return {"strategy": text}
    except Exception as exc:
        logger.error("Gemini strategy generation failed: %s", exc)
        return {"error": str(exc)}


def call_groq_for_strategy(patterns, run_data):
    if not GROQ_API_KEY:
        return {"error": "Groq unavailable"}
    prompt = _build_prompt(patterns, run_data)
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
                    {"role": "system", "content": "Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not text:
                    raise RuntimeError("Groq returned empty strategy content.")
                return {"strategy": text}
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                body = exc.response.text if exc.response is not None else str(exc)
                errors.append(f"{model_name} ({status}): {body[:220]}")
                low = body.lower()
                if status == 400 and json_mode and ("response_format" in low or "json_object" in low):
                    logger.warning("Groq strategy model %s rejected json mode; retrying without it.", model_name)
                    continue
                if status == 400 and ("decommissioned" in low or "no longer supported" in low):
                    logger.warning("Groq strategy model %s decommissioned; trying next model.", model_name)
                    break
                if status in (401, 403):
                    return {"error": f"Groq auth/permission failed ({status})."}
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")
                if json_mode:
                    continue
                break

    logger.error("Groq strategy generation failed: %s", " | ".join(errors[-4:]))
    return {"error": "Groq strategy generation failed"}


def intelligence_report(run_id, run_data, use_gemini: bool = True):
    data = query_engagement(run_id)
    patterns = compute_patterns(data)
    metrics = aggregate_engagement_metrics(data)
    if use_gemini:
        strategy = call_gemini_for_strategy(patterns, run_data)
        if "error" in strategy:
            strategy = call_groq_for_strategy(patterns, run_data)
    else:
        strategy = call_groq_for_strategy(patterns, run_data)
    if "error" in strategy:
        strategy = _fallback_strategy()
    return {"patterns": patterns, "metrics": metrics, "strategy": strategy}
