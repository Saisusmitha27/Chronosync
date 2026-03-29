import os
import logging

from agents.drafting_agent import draft_content
from agents.compliance_agent import review_content
from agents.brand_governance_agent import enforce_brand_rules
from agents.knowledge_agent import generate_from_document
from agents.localization_agent import localize_content
from agents.intelligence_agent import (
    intelligence_report,
    derive_project_strategy,
    load_project_strategy,
    query_recent_engagement,
)
from utils.supabase_client import insert_run, update_run

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _progress(callback, value: int, message: str):
    if callback:
        try:
            callback(int(value), message)
        except Exception:
            logger.debug("Progress callback failed", exc_info=True)


def _build_video_payloads(base_location: str, english_content: dict, localized_items: list):
    payloads = [
        {"location": f"{base_location}_english", "language": "english", "content": english_content}
    ]
    for item in localized_items:
        if item.get("language", "").lower() == "english":
            continue
        payloads.append(item)
    return payloads


def orchestrate(
    niche,
    audience,
    location,
    platform,
    tone,
    internal_data,
    target_locations,
    profile_map,
    approved=False,
    approver="unknown",
    localization_language="Auto",
    progress_callback=None,
    existing_run_id=None,
    existing_draft=None,
    existing_compliance=None,
    english_video_only=True,
    knowledge_file=None,
    regenerate_instruction="",
):
    project_key = f"{niche}|{audience}|{platform}|{location}".lower()
    content_strategy = load_project_strategy(project_key)
    if not content_strategy:
        recent_metrics_data = query_recent_engagement(limit=200)
        content_strategy = derive_project_strategy(project_key, recent_metrics_data)

    run_record = {
        "user_inputs": {
            "niche": niche,
            "audience": audience,
            "location": location,
            "platform": platform,
            "tone": tone,
            "target_locations": target_locations,
            "internal_data": internal_data,
            "localization_language": localization_language,
            "regenerate_instruction": regenerate_instruction,
        },
        
        "status": "drafting",
    }

    _progress(progress_callback, 5, "Initializing workflow...")
    run_id = existing_run_id
    if not run_id:
        try:
            insert_resp = insert_run(run_record)
            if hasattr(insert_resp, "data") and insert_resp.data:
                run_id = insert_resp.data[0].get("id")
        except Exception as exc:
            logger.warning("Run insert failed; continuing without DB persistence: %s", exc)

    if existing_draft:
        draft = existing_draft
        _progress(progress_callback, 50, "Using approved draft (no re-generation)...")
    else:
        _progress(progress_callback, 10, "Generating idea and hook...")
        if knowledge_file is not None:
            draft = generate_from_document(
                knowledge_file,
                niche=niche,
                audience=audience,
                location=location,
                platform=platform,
                tone=tone,
                extra_text=internal_data,
                content_strategy=content_strategy,
                regenerate_instruction=regenerate_instruction,
            )
        else:
            draft = draft_content(
                niche,
                audience,
                location,
                platform,
                tone,
                internal_data,
                content_strategy=content_strategy,
                regenerate_instruction=regenerate_instruction,
            )
        _progress(progress_callback, 30, "Building script for short-form video...")
        _progress(progress_callback, 50, "Structuring scenes...")

    brand_governance = enforce_brand_rules(draft.get("content", {}))
    if brand_governance.get("content"):
        draft["content"] = brand_governance["content"]
    draft["brand_governance"] = brand_governance

    if existing_compliance:
        compliance = existing_compliance
    else:
        compliance = review_content(draft["content"])

    if run_id:
        try:
            update_run(run_id, {"status": "compliance", "draft_json": draft, "compliance_json": compliance})
        except Exception as exc:
            logger.warning("Run compliance update failed (run_id=%s): %s", run_id, exc)

    compliance_status = str(compliance.get("compliance_status", "")).lower()
    if compliance_status != "approved" and not approved:
        _progress(progress_callback, 100, "Compliance review needed.")
        return {"run_id": run_id, "draft": draft, "compliance": compliance, "status": "needs_approval"}
    if compliance_status != "approved" and approved:
        logger.warning(
            "Proceeding after manual approval despite compliance status='%s' (approver=%s)",
            compliance_status,
            approver,
        )

    if not approved:
        _progress(progress_callback, 100, "Draft ready for approval.")
        return {"run_id": run_id, "draft": draft, "compliance": compliance, "status": "pending_approval"}

    if english_video_only:
        _progress(progress_callback, 55, "Preparing English video...")
        video_payloads = [
            {"location": f"{location}_english", "language": "english", "content": draft["content"]}
        ]
    else:
        _progress(progress_callback, 55, "Generating localized version...")
        localized = localize_content(
            draft["content"],
            target_locations=target_locations,
            forced_language=localization_language,
            use_gemini=False,
        )
        video_payloads = _build_video_payloads(location, draft["content"], localized)

    _progress(progress_callback, 70, "Fetching media for scenes...")
    print(f"[VIDEO] Starting render for {len(video_payloads)} payload(s)")
    videos = []
    total = max(len(video_payloads), 1)
    for idx, item in enumerate(video_payloads):
        try:
            from utils.video_builder import build_video

            script = item["content"].get("script", "")
            scenes = item["content"].get("scenes", [])
            loc_name = item.get("location", "output")
            lang = item.get("language", "unknown")
            file_name = f"video_{loc_name}_{lang}.mp4".replace(" ", "_")
            video_output = os.path.join(PROJECT_ROOT, file_name)

            current_progress = 70 + int(((idx + 1) / total) * 20)
            _progress(progress_callback, current_progress, f"Rendering video: {loc_name} ({lang})...")
            print(f"[VIDEO] Rendering: location={loc_name} language={lang} output={video_output}")

            video_path = build_video(
                script=script,
                output_path=video_output,
                scenes=scenes,
                tts_lang=lang,
            )
            if video_path and os.path.exists(video_path):
                videos.append({"location": loc_name, "language": lang, "video_path": video_path})
                logger.info("Video generated for %s (%s): %s", loc_name, lang, video_path)
                print(f"[VIDEO] Generated: {video_path}")
            else:
                logger.warning("Video generation returned no path for %s (%s)", loc_name, lang)
                print(f"[VIDEO] No path returned for {loc_name} ({lang})")
        except Exception as exc:
            logger.warning("Video generation failed for %s: %s", item.get("location", "?"), exc)
            print(f"[VIDEO ERROR] {item.get('location', '?')}: {exc}")

    _progress(progress_callback, 95, "Generating intelligence summary...")
    intel = intelligence_report(run_id, draft, use_gemini=False)

    final_json = {
        "draft": draft,
        "brand_governance": brand_governance,
        "strategy": content_strategy,
        "compliance": compliance,
        "localized": video_payloads,
        "distribution": [],
        "videos": videos,
        "intelligence": intel,
        "approved_by": approver,
    }
    print(f"[VIDEO] Completed with {len(videos)} video(s)")

    if run_id:
        try:
            update_run(run_id, {"status": "completed", "final_json": final_json, "approved_by": approver})
        except Exception as exc:
            logger.warning("Run completion update failed (run_id=%s): %s", run_id, exc)
    _progress(progress_callback, 100, "Done.")
    return {"run_id": run_id, "final": final_json, "status": "completed"}
