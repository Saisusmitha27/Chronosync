import logging
from pytrends.request import TrendReq

logging.basicConfig(level=logging.INFO)


def get_trends(location: str, niche: str, top_n: int = 5):
    """Fetch top trends for location and niche using pytrends."""
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        kw_list = [niche] if niche else ["technology"]
        pytrends.build_payload(kw_list, cat=0, timeframe='now 7-d', geo=location[:2].upper() if location else '')
        related = pytrends.related_queries().get(niche, {}).get('top')
        if related is not None and not related.empty:
            return related['query'].head(top_n).tolist()
        # fallback to suggest
        sug = pytrends.suggestions(keyword=niche)
        return [item['title'] for item in sug[:top_n]]
    except Exception as e:
        logging.warning('Trend fetch failed: %s', e)
        # fallback list
        return [f'{niche} trend {i}' for i in range(1, top_n + 1)]
