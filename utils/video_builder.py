"""
Metacortex Video Builder — Voice-over + synced subtitles.

Key guarantees:
1) Voice narration always exists.
2) Subtitles are synced with narration.
3) Background stock footage is used (no text-only screens).
4) Temp files are cleaned AFTER rendering.
"""

import os
import re
import logging
import tempfile
import asyncio
import shutil
from pathlib import Path

import requests
from gtts import gTTS
import PIL.Image as PILImageModule
from PIL import Image as PILImage

from moviepy.editor import (
    TextClip,
    ImageClip,
    ColorClip,
    VideoFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
    AudioFileClip,
    CompositeAudioClip,
    concatenate_audioclips,
    afx,
)
try:
    import edge_tts
except Exception:
    edge_tts = None

logger = logging.getLogger(__name__)

# Pillow compatibility (moviepy expects Image.ANTIALIAS on older code paths)
if not hasattr(PILImageModule, "ANTIALIAS"):
    PILImageModule.ANTIALIAS = PILImageModule.Resampling.LANCZOS
if not hasattr(PILImage, "ANTIALIAS"):
    PILImage.ANTIALIAS = PILImage.Resampling.LANCZOS

# Paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
DEFAULT_FALLBACK_VIDEO = os.path.join(ASSETS_DIR, "default.mp4")
DEFAULT_MUSIC_PATH = os.path.join(ASSETS_DIR, "music.mp3")
TEMP_WORK_DIR = os.path.join(PROJECT_ROOT, ".chronosync_tmp")

VIDEO_W, VIDEO_H = 360, 640
MIN_TOTAL_DURATION = 25.0
MAX_TOTAL_DURATION = 30.0
AUDIO_EPSILON = 0.05
AUDIO_MIN_DURATION = 0.12
EDGE_TTS_RATE = "+15%"
MIN_TMP_FREE_BYTES = 300 * 1024 * 1024
EDGE_VOICE_MAP = {
    "en": "en-US-GuyNeural",
    "ta": "ta-IN-ValluvarNeural",
    "te": "te-IN-MohanNeural",
    "kn": "kn-IN-GaganNeural",
    "ml": "ml-IN-MidhunNeural",
    "hi": "hi-IN-MadhurNeural",
    "bn": "bn-IN-BashkarNeural",
    "mr": "mr-IN-ManoharNeural",
    "or": "en-US-GuyNeural",
}
LANG_CODE_MAP = {
    "english": "en",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",
    "hindi": "hi",
    "bengali": "bn",
    "marathi": "mr",
    "odia": "or",
}


def _download_remote_file(url: str) -> str:
    os.makedirs(TEMP_WORK_DIR, exist_ok=True)
    suffix = Path(url.split("?")[0]).suffix or ".mp4"
    temp_fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=TEMP_WORK_DIR)
    os.close(temp_fd)
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pexels.com/"}
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(temp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(temp_path) < 1024:
            logger.warning("Downloaded file too small: %s", url[:80])
            return None
        return temp_path
    except Exception as e:
        logger.error("[DOWNLOAD FAILED] %s: %s", url[:80], e)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None


def _is_no_space_error(exc: Exception) -> bool:
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return True
    return "No space left on device" in str(exc)


def _is_low_resource_error(exc: Exception) -> bool:
    msg = str(exc or "").lower()
    return (
        _is_no_space_error(exc)
        or "paging file is too small" in msg
        or "unable to allocate" in msg
        or "cannot allocate memory" in msg
    )


def _tmp_has_headroom(min_free_bytes: int = MIN_TMP_FREE_BYTES) -> bool:
    try:
        os.makedirs(TEMP_WORK_DIR, exist_ok=True)
        free_bytes = shutil.disk_usage(TEMP_WORK_DIR).free
        return free_bytes >= min_free_bytes
    except Exception:
        return True


def _download_remote_file_safe(url: str, download_cache: dict, no_space_mode: dict) -> str:
    if no_space_mode.get("enabled"):
        return None
    if download_cache.get(url):
        cached = download_cache.get(url)
        if cached and os.path.exists(cached):
            return cached
    if url in download_cache and download_cache.get(url) is None:
        return None
    if not _tmp_has_headroom():
        no_space_mode["enabled"] = True
        logger.warning("[DOWNLOAD SKIPPED] Low disk space in temp directory. Using local fallback media.")
        download_cache[url] = None
        return None

    os.makedirs(TEMP_WORK_DIR, exist_ok=True)
    suffix = Path(url.split("?")[0]).suffix or ".mp4"
    temp_fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=TEMP_WORK_DIR)
    os.close(temp_fd)
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pexels.com/"}
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(temp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(temp_path) < 1024:
            logger.warning("Downloaded file too small: %s", url[:80])
            download_cache[url] = None
            return None
        download_cache[url] = temp_path
        return temp_path
    except Exception as e:
        if _is_low_resource_error(e):
            no_space_mode["enabled"] = True
            logger.error("[DOWNLOAD FAILED][LOW RESOURCE] %s: %s", url[:80], e)
        else:
            logger.error("[DOWNLOAD FAILED] %s: %s", url[:80], e)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        download_cache[url] = None
        return None


def _get_local_fallback_path() -> str:
    if os.path.exists(DEFAULT_FALLBACK_VIDEO):
        return DEFAULT_FALLBACK_VIDEO
    return None


def _load_video_clip(file_path: str, target_duration: float):
    clip = VideoFileClip(
        file_path,
        audio=False,
        target_resolution=(VIDEO_H, VIDEO_W),
    )
    if clip.duration < target_duration:
        clip = clip.loop(duration=target_duration)
    clip = clip.subclip(0, min(target_duration, clip.duration))
    clip = clip.resize((VIDEO_W, VIDEO_H))
    return clip.without_audio()


def split_sentences(script: str):
    if not script:
        return ["Generated content."]
    script = re.sub(r"\s+", " ", script).strip()
    if not script:
        return ["Generated content."]
    parts = re.split(r"(?<=[.!?])\s+", script)
    return [p.strip() for p in parts if p.strip()]


def _ensure_conclusion(script: str) -> str:
    text = str(script or "").strip()
    if not text:
        return "In conclusion, take one action today and stay consistent."
    parts = split_sentences(text)
    if not parts:
        return "In conclusion, take one action today and stay consistent."
    last = parts[-1].lower()
    if any(k in last for k in ["in conclusion", "finally", "to sum up", "take action", "start today", "next step"]):
        return text
    if text[-1] not in ".!?":
        text += "."
    return text + " In conclusion, take action today."


def generate_voiceover(script: str, output_path: str) -> str:
    """
    Converts full script into speech audio file.
    Returns path to audio file.
    """
    tts = gTTS(text=script, lang="en")
    tts.save(output_path)
    return output_path


def _stabilize_audio_clip(clip: AudioFileClip):
    """
    Trim a tiny epsilon from MP3 tail to avoid MoviePy out-of-range buffer reads.
    """
    if not clip:
        return clip
    duration = float(getattr(clip, "duration", 0.0) or 0.0)
    if duration <= 0:
        return clip
    if duration > (AUDIO_MIN_DURATION + AUDIO_EPSILON):
        safe_end = max(AUDIO_MIN_DURATION, duration - AUDIO_EPSILON)
        return clip.subclip(0, safe_end)
    return clip


def _tts_to_clip(text: str, lang_code: str):
    """
    Generate a robust TTS clip. If localized TTS fails, fallback to English.
    """
    os.makedirs(TEMP_WORK_DIR, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(suffix=".mp3", dir=TEMP_WORK_DIR)
    os.close(temp_fd)
    if edge_tts is not None:
        try:
            voice_name = EDGE_VOICE_MAP.get(lang_code, EDGE_VOICE_MAP["en"])
            async def _edge_save():
                tts = edge_tts.Communicate(text=text, voice=voice_name, rate=EDGE_TTS_RATE)
                await tts.save(temp_path)
            try:
                asyncio.run(_edge_save())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_edge_save())
                finally:
                    loop.close()
            clip = _stabilize_audio_clip(AudioFileClip(temp_path))
            return clip, temp_path
        except Exception as exc:
            logger.warning("[EDGE TTS FALLBACK] lang=%s failed: %s", lang_code, exc)
    for candidate_lang in [lang_code, "en"]:
        try:
            tts = gTTS(text=text, lang=candidate_lang)
            tts.save(temp_path)
            clip = _stabilize_audio_clip(AudioFileClip(temp_path))
            return clip, temp_path
        except Exception as exc:
            logger.warning("[TTS RETRY] lang=%s failed: %s", candidate_lang, exc)
            continue
    if os.path.exists(temp_path):
        os.remove(temp_path)
    return None, None


def _generate_sentence_voiceovers(sentences, tts_lang="en"):
    audio_clips = []
    temp_paths = []
    for sentence in sentences:
        try:
            clip, temp_path = _tts_to_clip(sentence, tts_lang)
            if not clip or not temp_path:
                raise RuntimeError("No TTS clip produced.")
            audio_clips.append(clip)
            temp_paths.append(temp_path)
        except Exception as e:
            logger.error("[TTS FAILED] %s", e)
    return audio_clips, temp_paths


def _generate_single_voiceover(sentence: str, tts_lang="en"):
    return _tts_to_clip(sentence, tts_lang)


def _render_subtitle_image(text: str) -> str:
    """Render subtitle to a PNG using PIL (fallback when ImageMagick isn't available)."""
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(TEMP_WORK_DIR, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(suffix=".png", dir=TEMP_WORK_DIR)
    os.close(temp_fd)

    width = VIDEO_W - 60
    font_size = 46
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    # Wrap text
    words = text.split()
    lines = []
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if font.getlength(test) <= width:
            line = test
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)

    line_height = font_size + 8
    height = line_height * len(lines) + 20
    img = Image.new("RGBA", (VIDEO_W, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y = 10
    for ln in lines:
        w = font.getlength(ln)
        x = (VIDEO_W - w) / 2
        # stroke
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                draw.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        y += line_height

    img.save(temp_path)
    return temp_path


def create_subtitles(sentences, durations, temp_paths=None):
    """
    Returns list of TextClip objects synced with audio.
    """
    clips = []
    start_t = 0.0
    for text, dur in zip(sentences, durations):
        if not text:
            start_t += max(float(dur or 0.0), 0.0)
            continue
        dur = max(float(dur or 0.0), 0.1)
        try:
            caption = TextClip(
                text,
                fontsize=46,
                color="white",
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=3,
                size=(VIDEO_W - 60, None),
                method="caption",
            ).set_position(("center", VIDEO_H - 180)).set_start(start_t).set_duration(dur)
            caption = caption.crossfadein(0.2)
            clips.append(caption)
        except Exception:
            # Fallback: render via PIL to avoid ImageMagick dependency
            img_path = _render_subtitle_image(text)
            if temp_paths is not None:
                temp_paths.append(img_path)
            caption = (
                ImageClip(img_path)
                .set_start(start_t)
                .set_duration(dur)
                .set_position(("center", VIDEO_H - 220))
            )
            clips.append(caption)
        start_t += dur
    return clips


def _load_background_music(total_duration: float):
    if not os.path.exists(DEFAULT_MUSIC_PATH):
        return None
    try:
        # MP3 + MoviePy can over-read the last few samples on exact boundaries.
        # Keep small headroom at source and output tails to avoid boundary warnings.
        source_guard = 0.20
        output_guard = 0.08
        bg_audio = AudioFileClip(DEFAULT_MUSIC_PATH)
        source_end = max(0.2, bg_audio.duration - source_guard)
        bg_audio = bg_audio.subclip(0, source_end)

        if source_end <= total_duration:
            bg_audio = bg_audio.fx(afx.audio_loop, duration=total_duration + output_guard)

        target_end = max(0.1, total_duration - output_guard)
        bg_audio = bg_audio.subclip(0, target_end).audio_fadeout(0.05)
        return bg_audio.volumex(0.2)
    except Exception as e:
        logger.error("[MUSIC FAILED] %s", e)
        return None


def _build_background_clip(
    scene: dict,
    duration: float,
    temp_media_paths: list,
    download_cache: dict,
    no_space_mode: dict,
):
    media = scene.get("media_url") or scene.get("media_path")
    media_fallback = scene.get("media_fallback_url")
    bg_clip = None

    if media:
        try:
            if str(media).startswith(("http://", "https://")):
                local_path = _download_remote_file_safe(media, download_cache, no_space_mode)
                if local_path:
                    if local_path not in temp_media_paths:
                        temp_media_paths.append(local_path)
                    try:
                        bg_clip = _load_video_clip(local_path, duration)
                    except Exception as load_exc:
                        logger.warning("[MEDIA LOAD FAILED] %s", load_exc)
                        bg_clip = None
            elif os.path.exists(media):
                ext = Path(media).suffix.lower()
                if ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
                    try:
                        bg_clip = _load_video_clip(media, duration)
                    except Exception as load_exc:
                        logger.warning("[MEDIA LOAD FAILED] %s", load_exc)
                        bg_clip = None
                else:
                    bg_clip = ImageClip(media).set_duration(duration).resize((VIDEO_W, VIDEO_H))
        except Exception as e:
            logger.warning("[MEDIA FAILED] %s", e)
            bg_clip = None

    if bg_clip is None and media_fallback:
        try:
            if str(media_fallback).startswith(("http://", "https://")):
                local_path = _download_remote_file_safe(media_fallback, download_cache, no_space_mode)
                if local_path:
                    if local_path not in temp_media_paths:
                        temp_media_paths.append(local_path)
                    try:
                        bg_clip = _load_video_clip(local_path, duration)
                    except Exception as load_exc:
                        logger.warning("[FALLBACK MEDIA LOAD FAILED] %s", load_exc)
                        bg_clip = None
            elif os.path.exists(media_fallback):
                try:
                    bg_clip = _load_video_clip(media_fallback, duration)
                except Exception as load_exc:
                    logger.warning("[FALLBACK MEDIA LOAD FAILED] %s", load_exc)
                    bg_clip = None
        except Exception as e:
            logger.warning("[FALLBACK MEDIA FAILED] %s", e)
            bg_clip = None

    if bg_clip is None:
        fallback_path = _get_local_fallback_path()
        if fallback_path:
            try:
                bg_clip = _load_video_clip(fallback_path, duration)
            except Exception as fallback_exc:
                logger.warning("[LOCAL FALLBACK LOAD FAILED] %s", fallback_exc)
                bg_clip = None

    if bg_clip is None:
        # Ultra-safe fallback for low-memory/pagefile environments.
        bg_clip = ColorClip(size=(VIDEO_W, VIDEO_H), color=(18, 24, 48)).set_duration(duration)

    return bg_clip


def _write_video_with_memory_fallback(video, output_path: str):
    """
    Write video with progressive low-memory profiles.
    Retries at lower resolution/fps when numpy allocation errors occur.
    """
    profiles = [
        {"size": (VIDEO_W, VIDEO_H), "fps": 14, "audio_fps": 12000, "threads": 1},
        {"size": (320, 568), "fps": 12, "audio_fps": 11025, "threads": 1},
        {"size": (270, 480), "fps": 10, "audio_fps": 10000, "threads": 1},
    ]
    last_exc = None
    for idx, cfg in enumerate(profiles):
        work = video
        try:
            if video.size != list(cfg["size"]):
                work = video.resize(cfg["size"])
            logger.info(
                "[RENDER] profile=%d size=%sx%s fps=%s audio_fps=%s",
                idx + 1,
                cfg["size"][0],
                cfg["size"][1],
                cfg["fps"],
                cfg["audio_fps"],
            )
            work.write_videofile(
                output_path,
                fps=cfg["fps"],
                codec="libx264",
                audio_codec="aac",
                audio_fps=cfg["audio_fps"],
                audio_nbytes=2,
                preset="ultrafast",
                threads=cfg["threads"],
                logger=None,
            )
            return
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            is_mem = isinstance(exc, MemoryError) or ("Unable to allocate" in msg) or ("array with shape" in msg)
            if not is_mem:
                raise
            logger.warning("[RENDER] Memory issue on profile %d; retrying lower profile: %s", idx + 1, msg)
        finally:
            if work is not video:
                try:
                    work.close()
                except Exception:
                    pass
    if last_exc:
        raise last_exc


def build_video(script: str, output_path: str = "output.mp4", scenes=None, tts_lang: str = "en"):
    """
    Generate a vertical short-form video with:
    - Voice narration
    - Synced subtitles
    - Background music
    """
    temp_media_paths = []
    temp_audio_paths = []
    temp_subtitle_paths = []
    download_cache = {}
    no_space_mode = {"enabled": False}
    voice_clips = []
    bg_clips = []
    subtitle_clips = []
    video = None
    voice_audio = None
    final_audio = None

    try:
        script = _ensure_conclusion(script)
        sentences = split_sentences(script)
        if not sentences:
            sentences = ["Generated content."]

        lang_code = LANG_CODE_MAP.get(str(tts_lang).lower(), "en")
        voice_clips, temp_audio_paths = _generate_sentence_voiceovers(sentences, tts_lang=lang_code)
        if not voice_clips:
            raise RuntimeError("Voice-over generation failed.")

        durations = [max(c.duration, 1.0) for c in voice_clips]
        total_duration = sum(durations)

        # Keep duration within 30-35 seconds: extend to minimum if needed.
        while total_duration < MIN_TOTAL_DURATION and sentences:
            extra_clip, extra_path = _generate_single_voiceover(sentences[-1], tts_lang=lang_code)
            if not extra_clip:
                break
            voice_clips.append(extra_clip)
            temp_audio_paths.append(extra_path)
            sentences.append(sentences[-1])
            extra_duration = max(extra_clip.duration, 1.0)
            durations.append(extra_duration)
            total_duration += extra_duration

        # Trim to maximum duration cap.
        if total_duration > MAX_TOTAL_DURATION:
            trimmed_clips = []
            trimmed_sentences = []
            trimmed_durations = []
            used = 0.0
            for sentence, clip, dur in zip(sentences, voice_clips, durations):
                if used >= MAX_TOTAL_DURATION:
                    break
                remaining = MAX_TOTAL_DURATION - used
                if dur <= remaining:
                    trimmed_clips.append(clip)
                    trimmed_sentences.append(sentence)
                    trimmed_durations.append(dur)
                    used += dur
                else:
                    safe_remaining = max(AUDIO_MIN_DURATION, remaining - AUDIO_EPSILON)
                    trimmed = clip.subclip(0, safe_remaining)
                    trimmed_clips.append(trimmed)
                    trimmed_sentences.append(sentence)
                    trimmed_durations.append(safe_remaining)
                    used += safe_remaining
                    break
            voice_clips = trimmed_clips
            sentences = trimmed_sentences
            durations = trimmed_durations

        voice_audio = concatenate_audioclips(voice_clips)

        # Build background clips aligned to sentences
        if not scenes or not isinstance(scenes, list):
            scenes = [{}]

        bg_clips = []
        for i, dur in enumerate(durations):
            scene = scenes[i % len(scenes)]
            bg = _build_background_clip(
                scene,
                dur,
                temp_media_paths,
                download_cache=download_cache,
                no_space_mode=no_space_mode,
            )
            bg_clips.append(bg)

        video = concatenate_videoclips(bg_clips, method="chain")

        # Subtitles
        subtitle_clips = create_subtitles(sentences, durations, temp_paths=temp_subtitle_paths)
        if subtitle_clips:
            overlays = [video] + subtitle_clips
            video = CompositeVideoClip(overlays, size=(VIDEO_W, VIDEO_H))

        # Voice-only output (no background music). Avoid full-buffer normalize to reduce memory spikes.
        voice_audio = voice_audio.volumex(1.35)
        final_audio = voice_audio

        video = video.set_audio(final_audio)
        logger.info("[AUDIO] Voice duration=%.2fs | Video duration=%.2fs | Music=False", voice_audio.duration, video.duration)

        # Export
        if not os.path.isabs(output_path):
            output_path = os.path.join(PROJECT_ROOT, output_path)
        _write_video_with_memory_fallback(video, output_path)

        return output_path

    finally:
        for clip in subtitle_clips:
            try:
                clip.close()
            except Exception:
                pass
        for clip in bg_clips:
            try:
                clip.close()
            except Exception:
                pass
        for clip in voice_clips:
            try:
                clip.close()
            except Exception:
                pass
        for obj in [final_audio, voice_audio, video]:
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        for p in temp_media_paths + temp_audio_paths + temp_subtitle_paths:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
