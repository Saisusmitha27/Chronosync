import os
from dotenv import load_dotenv

load_dotenv()

# --- AI / LLM : Gemini ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GEMINI_MODEL   = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash').strip()
GEMINI_API_URL = os.environ.get(
    'GEMINI_API_URL',
    f'https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent'
)

# --- AI / LLM : Groq ---
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '').strip()

_RAW_GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant').strip()
_DECOMMISSIONED_MODELS = {
    'llama3-70b-8192':    'llama-3.1-8b-instant',
    'llama3-8b-8192':     'llama-3.1-8b-instant',
    'llama2-70b-4096':    'llama-3.1-8b-instant',
    'mixtral-8x7b-32768': 'llama-3.1-8b-instant',
}
GROQ_MODEL = _DECOMMISSIONED_MODELS.get(_RAW_GROQ_MODEL, _RAW_GROQ_MODEL)
if GROQ_MODEL != _RAW_GROQ_MODEL:
    print(
        f"[config] WARNING: GROQ_MODEL '{_RAW_GROQ_MODEL}' is decommissioned. "
        f"Auto-corrected to '{GROQ_MODEL}'. Update your .env to silence this."
    )

# --- Supabase ---
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# --- Buffer ---
BUFFER_ACCESS_TOKEN = os.environ.get('BUFFER_ACCESS_TOKEN')

# --- YouTube ---
YOUTUBE_CLIENT_ID     = os.environ.get('YOUTUBE_CLIENT_ID', '').strip()
YOUTUBE_CLIENT_SECRET = os.environ.get('YOUTUBE_CLIENT_SECRET', '').strip()
YOUTUBE_REDIRECT_URI  = os.environ.get('YOUTUBE_REDIRECT_URI', 'http://localhost:8501/').strip()

# --- Stock Media APIs ---
PEXELS_API_KEY  = os.environ.get('PEXELS_API_KEY', '').strip()
PIXABAY_API_KEY = os.environ.get('PIXABAY_API_KEY', '').strip()

# --- Asset Paths ---
PROJECT_ROOT           = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR             = os.path.join(PROJECT_ROOT, 'assets')
DEFAULT_FALLBACK_VIDEO = os.path.join(ASSETS_DIR, 'default.mp4')
DEFAULT_MUSIC_PATH     = os.path.join(ASSETS_DIR, 'music.mp3')
SUPABASE_STORAGE_BUCKET = os.environ.get('SUPABASE_STORAGE_BUCKET', 'videos').strip()
BRAND_RULES_FILE        = os.environ.get('BRAND_RULES_FILE', 'brand_rules.txt')

# --- Startup validation ---
_errors   = []
_warnings = []

if not SUPABASE_URL or not SUPABASE_KEY:
    _errors.append('SUPABASE_URL and SUPABASE_KEY must be set in .env')

if not GEMINI_API_KEY and not GROQ_API_KEY:
    _warnings.append(
        'Neither GEMINI_API_KEY nor GROQ_API_KEY is set. '
        'All LLM calls will fail. Set at least one in your .env file.'
    )
else:
    if not GEMINI_API_KEY:
        _warnings.append('GEMINI_API_KEY not set — Gemini unavailable, using Groq only.')
    if not GROQ_API_KEY:
        _warnings.append('GROQ_API_KEY not set — Groq unavailable, using Gemini only.')

if not PEXELS_API_KEY:
    _warnings.append('PEXELS_API_KEY not set. Stock video lookups will fall back to Pixabay/local.')

if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
    _warnings.append('YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET not set. YouTube upload will not work.')

for w in _warnings:
    print(f'[config] WARNING: {w}')

if _errors:
    raise ValueError('\n'.join(_errors))