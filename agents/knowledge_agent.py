import io
import logging
from typing import Optional

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from docx import Document
except Exception:
    Document = None

from agents.drafting_agent import draft_content

logger = logging.getLogger(__name__)


def _safe_decode(raw: bytes) -> str:
    if not raw:
        return ""
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return ""


def extract_document_text(file) -> str:
    if file is None:
        return ""
    if isinstance(file, dict):
        name = str(file.get("name", "") or "")
        raw = file.get("data", b"") or b""
    else:
        name = getattr(file, "name", "") or ""
        raw = file.read()
        if hasattr(file, "seek"):
            file.seek(0)
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    text = ""
    try:
        if ext == "pdf":
            if PdfReader is None:
                logger.warning("pypdf not installed; PDF extraction unavailable.")
                return ""
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif ext == "docx":
            if Document is None:
                logger.warning("python-docx not installed; DOCX extraction unavailable.")
                return ""
            doc = Document(io.BytesIO(raw))
            text = "\n".join(p.text for p in doc.paragraphs if p.text)
        else:
            text = _safe_decode(raw)
    except Exception as exc:
        logger.warning("Document extraction failed (%s): %s", name, exc)
        text = _safe_decode(raw)
    return " ".join(text.split())


def generate_from_document(
    file,
    niche: str = "Enterprise content",
    audience: str = "Business audience",
    location: str = "Global",
    platform: str = "YouTube Shorts",
    tone: str = "Professional",
    extra_text: str = "",
    content_strategy: Optional[dict] = None,
    regenerate_instruction: str = "",
):
    """
    Extracts content and generates structured video-ready content.
    """
    extracted = extract_document_text(file)
    internal_data = " ".join([str(extra_text or "").strip(), extracted]).strip()
    return draft_content(
        niche=niche,
        audience=audience,
        location=location,
        platform=platform,
        tone=tone,
        internal_data=internal_data,
        content_strategy=content_strategy,
        regenerate_instruction=regenerate_instruction,
    )
