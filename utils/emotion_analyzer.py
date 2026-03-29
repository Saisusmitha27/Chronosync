import logging
from transformers import pipeline

logger = logging.getLogger(__name__)

# create once and reuse
try:
    EMOTION_PIPELINE = pipeline('text-classification', model='j-hartmann/emotion-english-distilroberta-base', device=-1)
except Exception as e:
    logger.warning('Failed to initialize emotion pipeline: %s', e)
    EMOTION_PIPELINE = None


def analyze_emotion(text: str):
    """Return primary emotion label for a text snippet."""
    if not EMOTION_PIPELINE:
        return {'label': 'neutral', 'score': 0.0}
    try:
        result = EMOTION_PIPELINE(text[:512])
        if isinstance(result, list) and result:
            top = max(result, key=lambda x: x.get('score', 0))
            return {'label': top.get('label', 'neutral'), 'score': float(top.get('score', 0.0))}
    except Exception as e:
        logger.error('Emotion analysis error: %s', e)
    return {'label': 'neutral', 'score': 0.0}
