import logging
from deep_translator import GoogleTranslator

LANGUAGE_MAP = {
    'tamil': 'ta',
    'telugu': 'te',
    'kannada': 'kn',
    'malayalam': 'ml',
    'odia': 'or',
    'bengali': 'bn',
    'marathi': 'mr',
    'hindi': 'hi',
    'english': 'en'
}

logger = logging.getLogger(__name__)


def translate_text(text: str, target_lang: str):
    target_lang_code = LANGUAGE_MAP.get(target_lang.lower()) or target_lang.lower()
    if not text:
        return ''
    try:
        return GoogleTranslator(source='auto', target=target_lang_code).translate(text)
    except Exception as e:
        logger.warning('Translation failed for %s to %s: %s', text, target_lang, e)
        return text
