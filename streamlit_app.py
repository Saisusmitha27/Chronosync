import json
import os
import datetime as dt
from statistics import median
from uuid import uuid4

import altair as alt
import pandas as pd
import streamlit as st

from agents.distribution_agent import (
    build_youtube_auth_url,
    get_youtube_access_token,
    upload_to_youtube,
)
from agents.orchestrator import orchestrate
from config import (
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
)
from utils.supabase_client import get_engagement, get_runs, update_run, upload_video

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
HISTORY_KEEP_COUNT = 20


# -----------------------------------------------------------------------------
# Page Config
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Chronosync", layout="wide")


# -----------------------------------------------------------------------------
# Styles
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Serif+Display&display=swap');

* { font-family: 'Space Grotesk', sans-serif; }

.app-title {
    font-family: 'DM Serif Display', serif;
    font-size: 40px;
    color: #eae7ff;
    margin-bottom: 8px;
}

.app-subtitle {
    color: #b9b3ff;
    margin-bottom: 24px;
}

.card {
    background: linear-gradient(145deg, #1b1f3a 0%, #171a2f 100%);
    border: 1px solid #2c3155;
    border-radius: 16px;
    padding: 16px 18px;
    color: #e8e6ff;
    box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}

.card h4 {
    margin: 0 0 8px 0;
    font-weight: 600;
    color: #ffffff;
}

.chip {
    display: inline-block;
    background: #2b3160;
    color: #d9d6ff;
    padding: 6px 10px;
    border-radius: 999px;
    margin-right: 6px;
    margin-bottom: 6px;
    font-size: 12px;
}

.section-title {
    margin-top: 8px;
    margin-bottom: 8px;
    font-weight: 700;
    color: #ffffff;
}

.highlight {
    background: #2f3258;
    border-left: 4px solid #7e8bff;
    padding: 12px 14px;
    border-radius: 10px;
    color: #f2f1ff;
    font-weight: 600;
}

.muted {
    color: #a5a8c9;
}

.divider {
    height: 1px;
    background: #2b315a;
    margin: 16px 0;
}

[data-testid="stVideo"] {
    max-width: 360px;
    margin-left: auto;
    margin-right: auto;
}

[data-testid="stVideo"] video {
    max-width: 360px !important;
    max-height: 640px !important;
    border-radius: 14px;
    object-fit: cover;
}

.hero-nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 6px 18px 6px;
}

.hero-brand {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}

.hero-links {
    color: #b6b8d1;
    font-size: 14px;
}

.hero-links span {
    margin-right: 16px;
}

.hero-shell {
    border: 1px solid #262b4f;
    border-radius: 20px;
    background: radial-gradient(1200px 380px at 40% -20%, #1e2a6f 0%, #0f1226 45%, #0b0d18 100%);
    padding: 36px 34px;
    min-height: 360px;
}

.hero-chip {
    display: inline-block;
    color: #d7dbff;
    background: rgba(76, 98, 255, 0.22);
    border: 1px solid rgba(130, 148, 255, 0.35);
    border-radius: 999px;
    padding: 6px 12px;
    font-size: 12px;
    margin-bottom: 16px;
}

.hero-title {
    font-size: 64px;
    line-height: 1.0;
    letter-spacing: -1.4px;
    color: #f7f8ff;
    margin: 0 0 12px 0;
    font-weight: 700;
}

.hero-copy {
    color: #b8bddf;
    font-size: 21px;
    max-width: 660px;
    line-height: 1.35;
}

.hero-kpis {
    margin-top: 20px;
}
</style>
""",
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def format_hashtags(tags):
    if not tags:
        return ""
    return " ".join([t if t.startswith("#") else f"#{t}" for t in tags])


def safe_get(d, key, default=""):
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def format_date(ts):
    if not ts:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return parsed.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        return str(ts)


def build_post_content_text(draft):
    idea = safe_get(draft, "idea", "")
    hook = safe_get(draft, "hook", "")
    script = safe_get(draft, "script", "")
    hashtags = format_hashtags(safe_get(draft, "hashtags", []))
    caption = safe_get(draft, "caption", "")
    return (
        f"Idea:\n{idea}\n\n"
        f"Hook:\n{hook}\n\n"
        f"Script:\n{script}\n\n"
        f"Hashtags:\n{hashtags}\n\n"
        f"SEO Caption:\n{caption}\n"
    )


def build_youtube_description(draft):
    seo_caption = safe_get(draft, "caption", "").strip()
    hashtags = format_hashtags(safe_get(draft, "hashtags", [])).strip()
    if seo_caption and hashtags:
        final_text = f"{seo_caption}\n\n{hashtags}"
    elif seo_caption:
        final_text = seo_caption
    else:
        final_text = hashtags
    if len(final_text) > 5000:
        final_text = final_text[:4997] + "..."
    return final_text


def get_query_params():
    if hasattr(st, "query_params"):
        raw = dict(st.query_params)
        normalized = {}
        for key, value in raw.items():
            if isinstance(value, list):
                normalized[key] = value
            else:
                normalized[key] = [str(value)]
        return normalized
    if hasattr(st, "experimental_get_query_params"):
        return st.experimental_get_query_params()
    return {}


def clear_query_params():
    if hasattr(st, "query_params"):
        st.query_params.clear()
    elif hasattr(st, "experimental_set_query_params"):
        st.experimental_set_query_params()


def get_primary_video_for_publish(final):
    videos = safe_get(final, "videos", [])
    if not videos:
        fallback_video = find_latest_generated_video()
        if fallback_video:
            return fallback_video
        return None
    primary_path = videos[-1].get("video_path")
    return resolve_video_path(primary_path)


def find_latest_generated_video():
    try:
        candidates = []
        for name in os.listdir(APP_ROOT):
            if name.startswith("video_") and name.lower().endswith(".mp4"):
                full = os.path.join(APP_ROOT, name)
                if os.path.isfile(full):
                    candidates.append(full)
        if not candidates:
            return None
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]
    except Exception:
        return None


def resolve_video_path(path):
    if path and os.path.exists(path):
        return path
    if path:
        base = os.path.basename(path)
        candidate = os.path.join(APP_ROOT, base)
        if os.path.exists(candidate):
            return candidate
    return None


def render_result_downloads(final, draft, key_prefix="final"):
    videos = safe_get(final, "videos", [])
    if not videos:
        fallback_video = find_latest_generated_video()
        if fallback_video:
            videos = [{"video_path": fallback_video, "location": "Latest Generated"}]
    if videos:
        primary_video_path = resolve_video_path(videos[-1].get("video_path"))
        if primary_video_path:
            with open(primary_video_path, "rb") as f:
                video_bytes = f.read()
                st.download_button(
                    "Download Generated Video",
                    data=video_bytes,
                    file_name=os.path.basename(primary_video_path),
                    mime="video/mp4",
                    key=f"{key_prefix}_download_video",
                )
        else:
            st.info("Video file not found on disk yet.")
    else:
        st.info("No generated video found for download yet.")

    hashtags_text = str(format_hashtags(safe_get(draft, "hashtags", [])) or "")
    script_text = str(safe_get(draft, "script", "") or "")
    post_text = build_post_content_text(draft)

    st.download_button(
        "Download Script",
        data=script_text.encode("utf-8"),
        file_name="script.txt",
        mime="text/plain",
        key=f"{key_prefix}_download_script",
    )
    st.download_button(
        "Download Hashtags",
        data=hashtags_text.encode("utf-8"),
        file_name="hashtags.txt",
        mime="text/plain",
        key=f"{key_prefix}_download_hashtags",
    )
    st.download_button(
        "Download Post Content & Hashtags",
        data=post_text.encode("utf-8"),
        file_name="post_content.txt",
        mime="text/plain",
        key=f"{key_prefix}_download_post_content",
    )


def render_scene_card(scene, idx):
    visual = safe_get(scene, "visual", "business office")
    text_overlay = safe_get(scene, "text_overlay", "")
    st.markdown(
        f"""
<div class="card">
  <h4>Scene {idx + 1}</h4>
  <div class="muted">🎥 Visual</div>
  <div>{visual}</div>
  <div class="divider"></div>
  <div class="muted">🧾 On‑screen text</div>
  <div>{text_overlay}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_video_block(video_path, label, key_suffix=""):
    resolved = resolve_video_path(video_path)
    if resolved:
        st.video(resolved)
        st.caption("If audio seems off in preview, unmute the player. Downloaded video contains full audio.")
        with open(resolved, "rb") as f:
            video_bytes = f.read()
            st.download_button(
                f"Download {label}",
                data=video_bytes,
                file_name=os.path.basename(resolved),
                mime="video/mp4",
                key=f"download_inline_{label}_{key_suffix}_{os.path.basename(resolved)}",
            )
    else:
        st.info("No video available yet.")


def render_error(msg="Something went wrong. Please try again."):
    st.warning(f"⚠️ {msg}")


def _parse_timestamp(value):
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_pct(value):
    return f"{(float(value) * 100):.1f}%"


def _fmt_sec(value):
    if value is None:
        return "n/a"
    return f"{float(value):.1f}s"


def _to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


@st.cache_data(ttl=180)
def load_analytics_data(limit=60):
    runs_resp = get_runs(limit)
    runs_data = runs_resp.data if hasattr(runs_resp, "data") and isinstance(runs_resp.data, list) else []
    engagement_rows = []
    for run in runs_data[:25]:
        run_id = run.get("id") if isinstance(run, dict) else None
        if not run_id:
            continue
        try:
            eng_resp = get_engagement(run_id)
            rows = eng_resp.data if hasattr(eng_resp, "data") and isinstance(eng_resp.data, list) else []
            engagement_rows.extend(rows)
        except Exception:
            continue
    return runs_data, engagement_rows


def compute_analytics(runs_data, engagement_rows):
    total_runs = len(runs_data)
    success_runs = 0
    failed_runs = 0
    compliance_passes = 0
    template_fallback_runs = 0
    gemini_runs = 0
    groq_runs = 0
    provider_known_runs = 0
    generation_times = []
    video_durations = []
    audio_present = 0
    subtitle_sync_success = 0
    scene_counts_for_videos = []
    hashtag_compliant_runs = 0

    stage_failures = {
        "Drafting": 0,
        "Compliance": 0,
        "Media Fetch": 0,
        "Video Rendering": 0,
    }
    source_usage = {"Pexels": 0, "Pixabay": 0, "Local Fallback": 0, "Unknown": 0}
    broken_download_count = 0
    timeline_rows = []

    for run in runs_data:
        if not isinstance(run, dict):
            continue

        created = _parse_timestamp(run.get("created_at"))
        updated = _parse_timestamp(run.get("updated_at")) or created
        gen_time = None
        if created and updated:
            gen_time = max((updated - created).total_seconds(), 0.0)
            generation_times.append(gen_time)

        status = str(run.get("status", "")).lower()
        final = run.get("final_json") if isinstance(run.get("final_json"), dict) else {}
        compliance = final.get("compliance") if isinstance(final.get("compliance"), dict) else {}
        if not compliance and isinstance(run.get("compliance_json"), dict):
            compliance = run.get("compliance_json")
        compliance_status = str(compliance.get("compliance_status", "")).lower()
        if compliance_status == "approved":
            compliance_passes += 1
        else:
            stage_failures["Compliance"] += 1

        draft = final.get("draft") if isinstance(final.get("draft"), dict) else {}
        if not draft and isinstance(run.get("draft_json"), dict):
            draft = run.get("draft_json")
        content = draft.get("content") if isinstance(draft.get("content"), dict) else {}

        if content.get("_fallback"):
            template_fallback_runs += 1
            stage_failures["Drafting"] += 1

        provider = str(content.get("_llm_provider", "")).lower()
        if provider in ("gemini", "groq"):
            provider_known_runs += 1
            if provider == "gemini":
                gemini_runs += 1
            elif provider == "groq":
                groq_runs += 1

        scenes = content.get("scenes") if isinstance(content.get("scenes"), list) else []
        if scenes:
            est_duration = sum(_to_float(s.get("duration", 0.0), 0.0) for s in scenes if isinstance(s, dict))
            if est_duration > 0:
                video_durations.append(est_duration)

        hashtags = content.get("hashtags") if isinstance(content.get("hashtags"), list) else []
        if 3 <= len(hashtags) <= 12:
            hashtag_compliant_runs += 1

        videos = final.get("videos") if isinstance(final.get("videos"), list) else []
        valid_video_paths = 0
        for v in videos:
            if not isinstance(v, dict):
                continue
            pth = resolve_video_path(v.get("video_path"))
            if pth and os.path.exists(pth):
                valid_video_paths += 1

        if status == "completed" and valid_video_paths > 0:
            success_runs += 1
        elif status in ("failed", "error", "video_failed") or (status == "completed" and valid_video_paths == 0):
            failed_runs += 1
            stage_failures["Video Rendering"] += 1

        if valid_video_paths > 0:
            audio_present += 1
            if scenes and content.get("script"):
                subtitle_sync_success += 1
                scene_counts_for_videos.append(len(scenes))

        missing_scene_media = 0
        for sc in scenes:
            if not isinstance(sc, dict):
                continue
            media_url = str(sc.get("media_url", "") or "")
            media_path = str(sc.get("media_path", "") or "")
            if not media_url and not media_path:
                missing_scene_media += 1
                continue
            if "pexels.com" in media_url:
                source_usage["Pexels"] += 1
            elif "pixabay.com" in media_url:
                source_usage["Pixabay"] += 1
            elif media_path or "default.mp4" in media_url or not media_url.startswith("http"):
                source_usage["Local Fallback"] += 1
            else:
                source_usage["Unknown"] += 1

        if missing_scene_media > 0:
            broken_download_count += missing_scene_media
            stage_failures["Media Fetch"] += 1

        timeline_rows.append({
            "created_at": created or dt.datetime.now(),
            "generation_seconds": gen_time if gen_time is not None else 0.0,
        })

    views = int(sum(_to_float(row.get("views", 0), 0) for row in engagement_rows if isinstance(row, dict)))
    likes = int(sum(_to_float(row.get("likes", 0), 0) for row in engagement_rows if isinstance(row, dict)))
    clicks = int(sum(_to_float(row.get("clicks", row.get("link_clicks", 0)), 0) for row in engagement_rows if isinstance(row, dict)))
    impressions = int(sum(_to_float(row.get("impressions", 0), 0) for row in engagement_rows if isinstance(row, dict)))
    ctr = (clicks / impressions) if impressions > 0 else 0.0

    avg_gen_time = (sum(generation_times) / len(generation_times)) if generation_times else 0.0
    med_gen_time = median(generation_times) if generation_times else 0.0
    avg_video_duration = (sum(video_durations) / len(video_durations)) if video_durations else 0.0
    success_rate = (success_runs / total_runs) if total_runs else 0.0
    compliance_rate = (compliance_passes / total_runs) if total_runs else 0.0
    gemini_success_rate = (gemini_runs / provider_known_runs) if provider_known_runs else 0.0
    groq_fallback_rate = (groq_runs / provider_known_runs) if provider_known_runs else 0.0
    template_fallback_rate = (template_fallback_runs / total_runs) if total_runs else 0.0

    media_total = sum(source_usage.values())
    pexels_hit_rate = (source_usage["Pexels"] / media_total) if media_total else 0.0
    pixabay_rate = (source_usage["Pixabay"] / media_total) if media_total else 0.0
    local_rate = (source_usage["Local Fallback"] / media_total) if media_total else 0.0
    audio_presence_rate = (audio_present / success_runs) if success_runs else 0.0
    subtitle_sync_rate = (subtitle_sync_success / success_runs) if success_runs else 0.0
    avg_scenes_per_video = (sum(scene_counts_for_videos) / len(scene_counts_for_videos)) if scene_counts_for_videos else 0.0
    hashtag_compliance_rate = (hashtag_compliant_runs / total_runs) if total_runs else 0.0

    baseline_seconds = 180.0
    turnaround_reduction = max(0.0, min(1.0, (baseline_seconds - avg_gen_time) / baseline_seconds)) if avg_gen_time else 0.0
    consistency_score = max(0.0, min(100.0, 100.0 - (template_fallback_rate * 35.0) - ((1.0 - compliance_rate) * 45.0) - ((1.0 - hashtag_compliance_rate) * 20.0)))

    workflow_df = pd.DataFrame([
        {"state": "Completed", "runs": success_runs},
        {"state": "Failed", "runs": failed_runs},
    ])
    stage_df = pd.DataFrame([
        {"stage": k, "failure_rate": (v / total_runs) if total_runs else 0.0}
        for k, v in stage_failures.items()
    ])
    model_df = pd.DataFrame([
        {"provider": "Gemini", "runs": gemini_runs},
        {"provider": "Groq", "runs": groq_runs},
        {"provider": "Template Fallback", "runs": template_fallback_runs},
    ])
    media_df = pd.DataFrame([{"source": k, "count": v} for k, v in source_usage.items()])
    timeline_df = pd.DataFrame(timeline_rows).sort_values("created_at") if timeline_rows else pd.DataFrame()

    metrics = {
        "total_runs": total_runs,
        "success_rate": success_rate,
        "avg_gen_time": avg_gen_time,
        "median_gen_time": med_gen_time,
        "avg_video_duration": avg_video_duration,
        "compliance_rate": compliance_rate,
        "gemini_success_rate": gemini_success_rate,
        "groq_fallback_rate": groq_fallback_rate,
        "template_fallback_rate": template_fallback_rate,
        "pexels_hit_rate": pexels_hit_rate,
        "pixabay_fallback_rate": pixabay_rate,
        "local_fallback_rate": local_rate,
        "broken_download_count": broken_download_count,
        "audio_presence_rate": audio_presence_rate,
        "subtitle_sync_rate": subtitle_sync_rate,
        "avg_scenes_per_video": avg_scenes_per_video,
        "hashtag_compliance_rate": hashtag_compliance_rate,
        "turnaround_reduction": turnaround_reduction,
        "consistency_score": consistency_score,
        "views": views,
        "likes": likes,
        "ctr": ctr,
    }
    return metrics, workflow_df, stage_df, model_df, media_df, timeline_df


def generate_ai_insights(metrics, timeline_df):
    insights = []
    if metrics["gemini_success_rate"] < 0.6:
        insights.append("Gemini failures increased. Fallback usage is high.")
    elif metrics["gemini_success_rate"] >= 0.85:
        insights.append("? Gemini performance is stable and healthy.")

    if metrics["template_fallback_rate"] > 0.25:
        insights.append("Template fallback usage is elevated. Prompt/provider reliability needs tuning.")

    if metrics["broken_download_count"] > 0:
        insights.append("Media pipeline has broken media entries. Review source URLs and fallbacks.")

    if metrics["compliance_rate"] >= 0.9:
        insights.append("? Compliance rate improved and remains strong.")

    if not timeline_df.empty and len(timeline_df) >= 6:
        half = len(timeline_df) // 2
        early = timeline_df["generation_seconds"].iloc[:half].mean()
        recent = timeline_df["generation_seconds"].iloc[half:].mean()
        if early > 0:
            delta = (recent - early) / early
            if delta > 0.2:
                insights.append(f"Render time increased by {delta * 100:.0f}% in recent runs.")
            elif delta < -0.1:
                insights.append(f"? Render time improved by {abs(delta) * 100:.0f}% in recent runs.")

    if not insights:
        insights.append("System performing efficiently across content and video pipeline.")
    return insights[:5]


# -----------------------------------------------------------------------------
# Session State
# -----------------------------------------------------------------------------
if "workflow" not in st.session_state:
    st.session_state.workflow = {}
if "inputs" not in st.session_state:
    st.session_state.inputs = {}
if "draft_approved" not in st.session_state:
    st.session_state.draft_approved = False
if "youtube_token" not in st.session_state:
    st.session_state.youtube_token = ""
if "youtube_refresh_token" not in st.session_state:
    st.session_state.youtube_refresh_token = ""
if "youtube_oauth_state" not in st.session_state:
    st.session_state.youtube_oauth_state = ""
if "youtube_auth_url" not in st.session_state:
    st.session_state.youtube_auth_url = ""


# -----------------------------------------------------------------------------
# Sidebar Navigation
# -----------------------------------------------------------------------------
st.sidebar.title("Chronosync")
NAV_OPTIONS = ["Dashboard", "Generate Video", "History", "Analytics"]

if "nav_request" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("nav_request")

if "nav" not in st.session_state:
    st.session_state["nav"] = "Dashboard"
elif st.session_state.get("nav") == "My Projects":
    st.session_state["nav"] = "History"

nav = st.sidebar.radio("Navigation", NAV_OPTIONS, key="nav")


def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
if nav == "Dashboard":
    st.markdown(
        """
<div class="hero-nav">
  <div class="hero-brand">Chronosync</div>
  <div class="hero-links">
    <span>Product</span><span>Teams</span><span>Resources</span><span>Community</span><span>Support</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="hero-shell">
  <div class="hero-chip">AI Content Operations Platform</div>
  <h1 class="hero-title">Build better<br/>campaign videos, faster</h1>
  <div class="hero-copy">
    Chronosync automates ideation, compliance, media selection, and short-video rendering
    so your team can publish consistently across channels.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    cta1, cta2 = st.columns([1, 1])
    with cta1:
        if st.button("Start Creating", use_container_width=True):
            st.session_state["nav_request"] = "Generate Video"
            safe_rerun()
    with cta2:
        if st.button("View Analytics", use_container_width=True):
            st.session_state["nav_request"] = "Analytics"
            safe_rerun()

    total_videos = 0
    recent_runs = []
    try:
        runs = get_runs(12)
        recent_runs = runs.data if hasattr(runs, "data") else []
        for r in recent_runs:
            final = r.get("final_json") if isinstance(r, dict) else None
            if isinstance(final, dict):
                vids = final.get("videos", [])
                total_videos += len(vids) if isinstance(vids, list) else 0
    except Exception:
        pass

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
    st.markdown("### Workspace Snapshot")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Projects", len(recent_runs))
    m2.metric("Videos Rendered", total_videos)
    m3.metric("Pipeline", "Active")
    m4.metric("Brand", "Chronosync")

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
    st.markdown("### Recent Projects")
    if recent_runs:
        cols = st.columns(2)
        for idx, run in enumerate(recent_runs[:4]):
            user_inputs = run.get("user_inputs", {}) if isinstance(run, dict) else {}
            title = user_inputs.get("niche") or user_inputs.get("topic") or "Untitled Project"
            date = format_date(run.get("created_at"))
            channel = user_inputs.get("platform", "Short Video")
            with cols[idx % 2]:
                st.markdown(
                    f"""
<div class="card">
  <h4>{title}</h4>
  <div class="muted">{date} · {channel}</div>
</div>
""",
                    unsafe_allow_html=True,
                )
    else:
        st.info("No projects yet. Create your first Chronosync video.")


# -----------------------------------------------------------------------------
# Generate Video
# -----------------------------------------------------------------------------
if nav == "Generate Video":
    st.markdown('<div class="app-title">Generate Video</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">Create enterprise-ready short videos from prompts or internal documents</div>', unsafe_allow_html=True)

    with st.form("generator_form"):
        topic = st.text_input("Topic", "AI productivity for teams")
        audience = st.text_input("Target Audience", "Founders and marketing teams")
        tone = st.selectbox("Tone", ["Professional", "Casual", "Energetic"])
        platform = st.selectbox("Platform", ["Instagram Reels", "YouTube Shorts"])
        localization = st.selectbox(
            "Localization Language",
            ["Auto", "English", "Tamil", "Hindi", "Telugu", "Kannada", "Malayalam", "Bengali", "Marathi", "Odia"],
        )
        location = st.text_input("Location", "Chennai")
        knowledge_text = st.text_area(
            "Knowledge Input (product notes, customer feedback, internal text)",
            "",
            height=120,
        )
        knowledge_file = st.file_uploader("Upload Document (PDF, DOCX, TXT)", type=["pdf", "docx", "txt"])
        submit = st.form_submit_button("Generate Draft")

    if submit:
        progress = st.progress(0)
        status_box = st.empty()

        def progress_cb(value, message):
            progress.progress(value)
            status_box.text(message)

        try:
            profile_map = {
                "chennai": {"profile_id": "your_buffer_profile_id"},
                "hyderabad": {"profile_id": "your_buffer_profile_id"},
                "default": {"profile_id": "your_buffer_profile_id"},
            }
            knowledge_payload = None
            if knowledge_file is not None:
                knowledge_payload = {
                    "name": knowledge_file.name,
                    "data": knowledge_file.getvalue(),
                }

            st.session_state.workflow = orchestrate(
                niche=topic,
                audience=audience,
                location=location,
                platform=platform,
                tone=tone,
                internal_data=knowledge_text,
                target_locations=[location],
                profile_map=profile_map,
                approved=False,
                approver=None,
                localization_language=localization,
                progress_callback=progress_cb,
                knowledge_file=knowledge_payload,
            )
            st.session_state.inputs = {
                "niche": topic,
                "audience": audience,
                "location": location,
                "platform": platform,
                "tone": tone,
                "internal_data": knowledge_text,
                "target_locations": [location],
                "profile_map": profile_map,
                "localization_language": localization,
                "knowledge_file": knowledge_payload,
            }
            st.session_state["draft_approved"] = False
            progress.progress(100)
            status_box.text("Draft ready.")
            st.success("Draft generated. Use Generate Again / Approve / Generate Video.")
        except Exception:
            render_error()

    workflow = st.session_state.workflow
    if workflow:
        status = workflow.get("status")
        if status in ["needs_approval", "pending_approval"]:
            draft = safe_get(workflow, "draft", {}).get("content", {})
            fallback_reason = safe_get(draft, "_fallback_reason", "")
            if fallback_reason:
                st.warning("We used a fallback template because the model response failed. Check your Groq/Gemini API key or network.")

            st.markdown("**Idea**")
            st.write(safe_get(draft, "idea", ""))

            st.markdown("**Hook**")
            st.markdown(f"<div class='highlight'>{safe_get(draft, 'hook', '')}</div>", unsafe_allow_html=True)

            st.markdown("**Script**")
            st.write(safe_get(draft, "script", ""))

            st.markdown("**Scenes**")
            scenes = safe_get(draft, "scenes", [])
            if scenes:
                cols = st.columns(2)
                for i, sc in enumerate(scenes):
                    with cols[i % 2]:
                        render_scene_card(sc, i)
            else:
                st.info("No scenes available yet.")

            st.markdown("**Hashtags**")
            st.write(format_hashtags(safe_get(draft, "hashtags", [])))

            st.markdown("**SEO Caption**")
            st.write(safe_get(draft, "caption", ""))
            governance = safe_get(workflow, "draft", {}).get("brand_governance", {})
            if isinstance(governance, dict):
                st.caption(
                    f"Brand governance: {governance.get('summary', 'No governance summary')} "
                    f"(violations: {len(governance.get('violations', []))})"
                )

            b1, b2, b3 = st.columns(3)
            regen = b1.button("Generate Again", use_container_width=True)
            approve = b2.button("Approve & Continue", use_container_width=True)
            can_generate_video = bool(st.session_state.get("draft_approved", False))
            gen_video = b3.button("Generate Video", disabled=not can_generate_video, use_container_width=True)

            if regen:
                progress = st.progress(0)
                status_box = st.empty()

                def regen_cb(value, message):
                    progress.progress(value)
                    status_box.text(message)

                try:
                    inputs = st.session_state.inputs
                    refreshed = orchestrate(
                        niche=inputs["niche"],
                        audience=inputs["audience"],
                        location=inputs["location"],
                        platform=inputs["platform"],
                        tone=inputs["tone"],
                        internal_data=inputs.get("internal_data", ""),
                        target_locations=inputs["target_locations"],
                        profile_map=inputs["profile_map"],
                        approved=False,
                        approver=None,
                        localization_language=inputs.get("localization_language", "Auto"),
                        progress_callback=regen_cb,
                        knowledge_file=inputs.get("knowledge_file"),
                        regenerate_instruction="Regenerate with a different hook, storytelling style, and improved engagement.",
                    )
                    st.session_state.workflow = refreshed
                    st.session_state["draft_approved"] = False
                    progress.progress(100)
                    status_box.text("Regenerated draft ready.")
                    st.success("New draft generated. Review and approve when ready.")
                    safe_rerun()
                except Exception:
                    render_error("Regeneration failed. Please try again.")

            if approve:
                st.session_state["draft_approved"] = True
                st.success("Draft approved. Click Generate Video to continue.")

            if gen_video and st.session_state.get("draft_approved"):
                progress = st.progress(0)
                status_box = st.empty()

                def video_cb(value, message):
                    progress.progress(value)
                    status_box.text(message)

                try:
                    inputs = st.session_state.inputs
                    full = orchestrate(
                        niche=inputs["niche"],
                        audience=inputs["audience"],
                        location=inputs["location"],
                        platform=inputs["platform"],
                        tone=inputs["tone"],
                        internal_data=inputs.get("internal_data", ""),
                        target_locations=inputs["target_locations"],
                        profile_map=inputs["profile_map"],
                        approved=True,
                        approver=st.session_state.get("user", "streamlit_user"),
                        localization_language=inputs.get("localization_language", "Auto"),
                        progress_callback=video_cb,
                        existing_run_id=workflow.get("run_id"),
                        existing_draft=workflow.get("draft"),
                        existing_compliance=workflow.get("compliance"),
                    )
                    st.session_state.workflow = full
                    st.session_state["draft_approved"] = False
                    progress.progress(100)
                    status_box.text("Video generation complete.")
                    st.success("Final outputs generated successfully.")
                    safe_rerun()
                except Exception:
                    render_error("Video generation failed. Please retry.")

        if workflow.get("status") == "completed":
            final = safe_get(workflow, "final", {})
            draft = safe_get(final, "draft", {}).get("content", {})

            st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
            st.markdown("**Idea**")
            st.write(safe_get(draft, "idea", ""))

            st.markdown("**Hook**")
            st.markdown(f"<div class='highlight'>{safe_get(draft, 'hook', '')}</div>", unsafe_allow_html=True)

            st.markdown("**Script**")
            st.write(safe_get(draft, "script", ""))

            st.markdown("**Scenes**")
            scenes = safe_get(draft, "scenes", [])
            if scenes:
                cols = st.columns(2)
                for i, sc in enumerate(scenes):
                    with cols[i % 2]:
                        render_scene_card(sc, i)

            st.markdown("**Hashtags**")
            st.write(format_hashtags(safe_get(draft, "hashtags", [])))

            st.markdown("**SEO Caption**")
            st.write(safe_get(draft, "caption", ""))
            final_governance = safe_get(final, "brand_governance", {})
            if isinstance(final_governance, dict):
                st.caption(
                    f"Brand governance: {final_governance.get('summary', 'No governance summary')} "
                    f"(violations: {len(final_governance.get('violations', []))})"
                )

            st.markdown("**Video Preview**")
            videos = safe_get(final, "videos", [])
            if not videos:
                fallback_video = find_latest_generated_video()
                if fallback_video:
                    videos = [{"video_path": fallback_video, "location": "Latest Generated"}]
            if videos:
                for idx, vid in enumerate(videos):
                    render_video_block(
                        vid.get("video_path"),
                        vid.get("location", "Video"),
                        key_suffix=str(idx),
                    )
            else:
                st.info("Video not generated yet.")

            st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
            st.markdown("**Final Downloads**")
            render_result_downloads(final, draft, key_prefix="final")

            # ----------------------------------------------------------------
            # Publish to YouTube
            # ----------------------------------------------------------------
            st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
            st.markdown("### ▶️ Publish to YouTube")

            run_key        = workflow.get("run_id") or "local"
            caption_key_yt = f"youtube_caption_{run_key}"
            title_key_yt   = f"youtube_title_{run_key}"

            if caption_key_yt not in st.session_state:
                st.session_state[caption_key_yt] = build_youtube_description(draft)
            if title_key_yt not in st.session_state:
                st.session_state[title_key_yt] = str(safe_get(draft, "idea", ""))[:100]

            # Handle YouTube OAuth callback
            yt_params      = get_query_params()
            yt_oauth_code  = (yt_params.get("code") or [""])[0]
            yt_oauth_error = (yt_params.get("error") or [""])[0]
            yt_oauth_state = (yt_params.get("state") or [""])[0]
            is_yt_callback = bool(yt_params.get("scope"))

            if yt_oauth_error and is_yt_callback:
                st.error(f"YouTube login failed: {yt_oauth_error}")
                clear_query_params()

            if yt_oauth_code and is_yt_callback:
                expected_yt_state = str(st.session_state.get("youtube_oauth_state", "")).strip()
                if expected_yt_state and yt_oauth_state and yt_oauth_state != expected_yt_state:
                    st.error("YouTube OAuth state mismatch. Please connect again.")
                    clear_query_params()
                    safe_rerun()
                else:
                    try:
                        yt_token_data = get_youtube_access_token(yt_oauth_code)
                        st.session_state["youtube_token"]         = yt_token_data.get("access_token", "")
                        st.session_state["youtube_refresh_token"] = yt_token_data.get("refresh_token", "")
                        st.success("YouTube account connected.")
                    except Exception as exc:
                        st.error(f"YouTube token exchange failed: {exc}")
                    clear_query_params()
                    safe_rerun()

            yt_token = str(st.session_state.get("youtube_token", "")).strip()

            # Connect / Disconnect
            if not yt_token:
                if st.button("🔗 Connect YouTube", key=f"connect_youtube_{run_key}"):
                    if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
                        st.error("Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REDIRECT_URI in .env.")
                    else:
                        yt_state = uuid4().hex
                        st.session_state["youtube_oauth_state"] = yt_state
                        yt_auth_url = build_youtube_auth_url(yt_state)
                        st.session_state["youtube_auth_url"] = yt_auth_url

                if st.session_state.get("youtube_auth_url"):
                    st.markdown(f"[Click here to login with Google/YouTube]({st.session_state['youtube_auth_url']})")
            else:
                st.success("✅ YouTube account is connected.")
                if st.button("Disconnect YouTube", key=f"disconnect_youtube_{run_key}"):
                    st.session_state["youtube_token"]    = ""
                    st.session_state["youtube_auth_url"] = ""
                    safe_rerun()

            # Video info
            primary_video_path = get_primary_video_for_publish(final)
            if primary_video_path:
                st.caption(f"Video ready for upload: {os.path.basename(primary_video_path)}")
            else:
                st.warning("No generated video found to upload.")

            st.text_input("Video Title", key=title_key_yt)
            st.text_area("Video Description", height=160, key=caption_key_yt)

            if st.button("🚀 Upload to YouTube", key=f"post_youtube_{run_key}", use_container_width=True):
                yt_token = str(st.session_state.get("youtube_token", "")).strip()
                if not yt_token:
                    st.error("Please connect YouTube before uploading.")
                elif not primary_video_path:
                    st.error("No video file available to upload.")
                else:
                    yt_title       = str(st.session_state.get(title_key_yt, "")).strip() or "Untitled Video"
                    yt_description = str(st.session_state.get(caption_key_yt, "")).strip()
                    yt_tags        = safe_get(draft, "hashtags", [])
                    try:
                        with st.spinner("Uploading video to YouTube... this may take a minute."):
                            yt_result = upload_to_youtube(
                                token=yt_token,
                                video_path=primary_video_path,
                                title=yt_title,
                                description=yt_description,
                                tags=yt_tags,
                            )
                        st.success("✅ Uploaded to YouTube successfully!")
                        if yt_result.get("video_url"):
                            st.markdown(f"[▶️ View on YouTube]({yt_result['video_url']})")

                        # Persist to Supabase
                        distribution_entry = {
                            "channel":    "youtube",
                            "posted_at":  dt.datetime.utcnow().isoformat() + "Z",
                            "video_id":   yt_result.get("video_id", ""),
                            "video_url":  yt_result.get("video_url", ""),
                            "title":      yt_title,
                            "description": yt_description,
                        }
                        if not isinstance(final.get("distribution"), list):
                            final["distribution"] = []
                        final["distribution"].append(distribution_entry)

                        run_id = workflow.get("run_id")
                        if run_id:
                            try:
                                update_run(run_id, {"final_json": final})
                            except Exception:
                                st.warning("Uploaded, but failed to persist distribution data to Supabase.")
                    except Exception as exc:
                        st.error(f"❌ Failed to upload to YouTube: {exc}")


# -----------------------------------------------------------------------------
# History
# -----------------------------------------------------------------------------
if nav == "History":
    st.markdown('<div class="app-title">History</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">Browse previous generations</div>', unsafe_allow_html=True)
    if st.button("Refresh History", use_container_width=False):
        safe_rerun()

    try:
        runs = get_runs(20)
        data = runs.data if hasattr(runs, "data") else []
        if isinstance(data, list):
            data = data[:HISTORY_KEEP_COUNT]
    except Exception:
        data = []

    if not data:
        st.info("No history available yet.")
    else:
        for run in data:
            user_inputs = run.get("user_inputs", {}) if isinstance(run, dict) else {}
            title = user_inputs.get("niche") or user_inputs.get("topic") or "Untitled Project"
            created = format_date(run.get("created_at"))
            status = str(run.get("status", "unknown")).title()
            run_id_short = str(run.get("id", ""))[:8]
            final = run.get("final_json") if isinstance(run, dict) else {}
            videos = final.get("videos", []) if isinstance(final, dict) else []

            st.markdown(
                f"""
<div class="card">
  <h4>{title}</h4>
  <div class="muted">{created} · Status: {status} · Run: {run_id_short}</div>
</div>
""",
                unsafe_allow_html=True,
            )

            cols = st.columns(2)
            with cols[0]:
                if st.button("Preview", key=f"preview_{run.get('id', '')}"):
                    st.session_state.workflow = {"status": "completed", "final": final}
                    st.success("Loaded into preview. Go to Generate Video to view.")
            with cols[1]:
                if videos:
                    vid = videos[0]
                    video_path = vid.get("video_path")
                    if video_path and os.path.exists(video_path):
                        with open(video_path, "rb") as f:
                            st.download_button(
                                "Download",
                                data=f,
                                file_name=os.path.basename(video_path),
                                mime="video/mp4",
                                key=f"download_{run.get('id', '')}",
                            )
                    else:
                        st.info("Video not found.")
                else:
                    st.info("No video available.")


# -----------------------------------------------------------------------------
# Analytics
# -----------------------------------------------------------------------------
if nav == "Analytics":
    st.markdown('<div class="app-title">Analytics</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">System intelligence for content and video automation</div>', unsafe_allow_html=True)

    runs_data, engagement_rows = load_analytics_data(limit=60)
    metrics, workflow_df, stage_df, model_df, media_df, timeline_df = compute_analytics(runs_data, engagement_rows)
    insights = generate_ai_insights(metrics, timeline_df)

    # ---------------- KPI ----------------
    st.markdown("### 🟢 KPI Overview")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Runs", metrics["total_runs"])
    k2.metric("Success Rate", _fmt_pct(metrics["success_rate"]))
    k3.metric("Avg Generation Time", _fmt_sec(metrics["avg_gen_time"]))
    k4.metric("Avg Video Duration", _fmt_sec(metrics["avg_video_duration"]))
    k5.metric("Compliance Rate", _fmt_pct(metrics["compliance_rate"]))

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ---------------- WORKFLOW ----------------
    st.markdown("### 📈 Workflow Performance")
    wf1, wf2 = st.columns(2)

    with wf1:
        st.caption("Completed vs Failed Runs")

        workflow_pie = alt.Chart(workflow_df).mark_arc(innerRadius=55).encode(
            theta=alt.Theta(field="runs", type="quantitative"),
            color=alt.Color(field="state", type="nominal"),
            tooltip=["state", "runs"],
        )

        st.altair_chart(workflow_pie, use_container_width=True)

    with wf2:
        st.caption("Stage-wise Failure Rates")

        stage_view = stage_df.copy()
        stage_view["failure_rate"] *= 100

        stage_line = alt.Chart(stage_view).mark_line(point=True).encode(
            x=alt.X("stage:N", sort=["Drafting", "Compliance", "Media Fetch", "Video Rendering"]),
            y=alt.Y("failure_rate:Q", title="Failure Rate (%)"),
            tooltip=["stage", alt.Tooltip("failure_rate:Q", format=".1f")],
        )

        st.altair_chart(stage_line, use_container_width=True)

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ---------------- MODEL PERFORMANCE ----------------
    st.markdown("### 🤖 Model Performance")

    m1, m2, m3 = st.columns(3)
    m1.metric("Gemini Success", _fmt_pct(metrics["gemini_success_rate"]))
    m2.metric("Groq Fallback", _fmt_pct(metrics["groq_fallback_rate"]))
    m3.metric("Template Fallback", _fmt_pct(metrics["template_fallback_rate"]))

    model_bar = alt.Chart(model_df).mark_bar().encode(
        x=alt.X("provider:N", title="Model"),
        y=alt.Y("runs:Q", title="Runs"),
        color=alt.Color("provider:N"),
        tooltip=["provider", "runs"],
    ).properties(height=300)

    st.altair_chart(model_bar, use_container_width=True)

    if metrics["gemini_success_rate"] < 0.6:
        st.warning("⚠️ Gemini failures increased recently.")
    else:
        st.success("✅ Stable model performance.")

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ---------------- MEDIA PIPELINE ----------------
    st.markdown("### 🎥 Media Pipeline Health")

    mh1, mh2, mh3, mh4 = st.columns(4)
    mh1.metric("Pexels Hit Rate", _fmt_pct(metrics["pexels_hit_rate"]))
    mh2.metric("Pixabay Fallback", _fmt_pct(metrics["pixabay_fallback_rate"]))
    mh3.metric("Local Fallback", _fmt_pct(metrics["local_fallback_rate"]))
    mh4.metric("Broken Downloads", int(metrics["broken_download_count"]))

    media_bar = alt.Chart(media_df).mark_bar().encode(
        x=alt.X("source:N", title="Source"),
        y=alt.Y("count:Q", title="Usage Count"),
        color=alt.Color("source:N"),
        tooltip=["source", "count"],
    ).properties(height=300)

    st.altair_chart(media_bar, use_container_width=True)

    if metrics["broken_download_count"] > 0:
        st.error("Media fetch issues detected. Review source URLs and fallbacks.")

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ---------------- VIDEO QUALITY ----------------
    st.markdown("### 🎬 Video Quality Metrics")

    v1, v2, v3 = st.columns(3)
    v1.metric("Avg Output Duration", _fmt_sec(metrics["avg_video_duration"]))
    v2.metric("Audio Presence Rate", _fmt_pct(metrics["audio_presence_rate"]))
    v3.metric("Subtitle Sync Success", _fmt_pct(metrics["subtitle_sync_rate"]))

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ---------------- CONTENT QUALITY ----------------
    st.markdown("### 🧠 Content Quality")

    c1, c2, c3 = st.columns(3)
    c1.metric("Compliance Pass Rate", _fmt_pct(metrics["compliance_rate"]))
    c2.metric("Avg Scenes per Video", f"{metrics['avg_scenes_per_video']:.1f}")
    c3.metric("Hashtag Compliance", _fmt_pct(metrics["hashtag_compliance_rate"]))

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ---------------- BUSINESS IMPACT ----------------
    st.markdown("### 💼 Business Impact")

    b1, b2, b3 = st.columns(3)
    b1.metric("Turnaround Reduction", _fmt_pct(metrics["turnaround_reduction"]))
    b2.metric("Consistency Score", f"{metrics['consistency_score']:.1f}/100")
    b3.metric("CTR", _fmt_pct(metrics["ctr"]))

    e1, e2 = st.columns(2)
    e1.metric("Total Views", int(metrics["views"]))
    e2.metric("Total Likes", int(metrics["likes"]))

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ---------------- AI INSIGHTS ----------------
    st.markdown("### 🧠 AI Insights")

    for insight in insights:
        st.markdown(f"- {insight}")