import json
import logging
import os
from urllib.parse import quote

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

from config import (
    BUFFER_ACCESS_TOKEN,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REDIRECT_URI,
)

BUFFER_API_URL    = 'https://api.buffer.com/1'
YOUTUBE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
YOUTUBE_TOKEN_URL     = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL    = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_SCOPES        = "https://www.googleapis.com/auth/youtube.upload"

logger = logging.getLogger(__name__)


# =============================================================================
# Buffer
# =============================================================================

def post_to_buffer(profile_id: str, text: str, media_url: str = None):
    if not BUFFER_ACCESS_TOKEN:
        raise RuntimeError('BUFFER_ACCESS_TOKEN is not configured')
    try:
        payload = {'profile_ids[]': profile_id, 'text': text}
        if media_url:
            payload['media[]'] = media_url
        headers = {'Authorization': f'Bearer {BUFFER_ACCESS_TOKEN}'}
        resp = requests.post(
            f'{BUFFER_API_URL}/updates/create.json',
            params=payload,
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error('Buffer posting failed: %s', e)
        return {'error': str(e)}


# =============================================================================
# YouTube — Auth
# =============================================================================

def build_youtube_auth_url(state: str):
    client_id    = str(YOUTUBE_CLIENT_ID or "").strip()
    redirect_uri = str(YOUTUBE_REDIRECT_URI or "").strip()
    if not client_id or not redirect_uri:
        raise RuntimeError("YOUTUBE_CLIENT_ID and YOUTUBE_REDIRECT_URI must be configured")
    return (
        f"{YOUTUBE_AUTH_BASE_URL}?response_type=code"
        f"&client_id={quote(client_id, safe='')}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        f"&scope={quote(YOUTUBE_SCOPES, safe='')}"
        f"&state={quote(str(state or ''), safe='')}"
        f"&access_type=offline"
        f"&prompt=consent"
    )


def get_youtube_access_token(code: str):
    client_id     = str(YOUTUBE_CLIENT_ID or "").strip()
    client_secret = str(YOUTUBE_CLIENT_SECRET or "").strip()
    redirect_uri  = str(YOUTUBE_REDIRECT_URI or "").strip()

    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REDIRECT_URI must be configured"
        )

    data = {
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  redirect_uri,
        "client_id":     client_id,
        "client_secret": client_secret,
    }
    response = requests.post(YOUTUBE_TOKEN_URL, data=data, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"YouTube token exchange failed ({response.status_code}): {response.text}")

    token_payload = response.json() if response.content else {}
    access_token  = token_payload.get("access_token")
    if not access_token:
        raise RuntimeError("YouTube token exchange did not return access_token")

    return {
        "access_token":  access_token,
        "refresh_token": token_payload.get("refresh_token", ""),
        "expires_in":    token_payload.get("expires_in"),
    }


# =============================================================================
# YouTube — Upload
# =============================================================================

def upload_to_youtube(token: str, video_path: str, title: str, description: str, tags: list = None):
    """
    Upload a video to YouTube.
    video_path: local file path OR public URL.
    Returns dict with video_id and video_url.
    """
    access_token = str(token or "").strip()
    if not access_token:
        raise RuntimeError("YouTube access token is missing")
    if not video_path:
        raise RuntimeError("YouTube video path is missing")
    if not title:
        title = "Untitled Video"
    if len(description) > 5000:
        description = description[:4997] + "..."

    # Load video bytes
    if video_path.startswith("http://") or video_path.startswith("https://"):
        logger.info("Downloading video from URL for YouTube upload...")
        r = requests.get(video_path, timeout=120)
        r.raise_for_status()
        video_bytes = r.content
    else:
        if not os.path.exists(video_path):
            raise RuntimeError(f"Video file not found: {video_path}")
        with open(video_path, "rb") as f:
            video_bytes = f.read()

    metadata = {
        "snippet": {
            "title":       title[:100],
            "description": description,
            "tags":        tags or [],
            "categoryId":  "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": "public",
        },
    }

    mp = MultipartEncoder(
        fields={
            "metadata": ("metadata.json", json.dumps(metadata), "application/json; charset=UTF-8"),
            "video":    ("video.mp4", video_bytes, "video/mp4"),
        }
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  mp.content_type,
    }

    response = requests.post(
        f"{YOUTUBE_UPLOAD_URL}?uploadType=multipart&part=snippet,status",
        headers=headers,
        data=mp,
        timeout=300,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(f"YouTube upload failed ({response.status_code}): {response.text}")

    data      = response.json() if response.content else {}
    video_id  = data.get("id", "")
    video_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

    return {
        "ok":        True,
        "video_id":  video_id,
        "video_url": video_url,
        "response":  data,
    }


# =============================================================================
# Distribute
# =============================================================================

def distribute(localized_content: list, profile_map: dict):
    results = []
    for item in localized_content:
        loc = item.get('location')
        cfg = profile_map.get(loc.lower()) or profile_map.get('default')
        if not cfg:
            logger.warning('No Buffer profile for location %s - skipping', loc)
            continue
        text  = item['content'].get('caption') or item['content'].get('script', '')
        media = item['content'].get('video_url')
        res   = post_to_buffer(cfg['profile_id'], text, media)
        results.append({'location': loc, 'profile': cfg, 'result': res})
    return results