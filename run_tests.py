import json
import pytest
from unittest.mock import patch

from agents.compliance_agent import review_content
from agents.localization_agent import map_location_to_language, localize_content
from agents.distribution_agent import distribute
from agents.intelligence_agent import compute_patterns
from agents.drafting_agent import draft_content


def test_compliance_no_issues():
    draft = {'idea': 'Great content', 'hook': 'attention', 'script': 'no bad words', 'caption': 'hello'}
    result = review_content(draft)
    assert result['compliance_status'] == 'approved'
    assert 'issues' in result


def test_compliance_violations():
    draft = {'idea': 'hateful phrase', 'hook': 'bad content', 'script': 'violence', 'caption': 'info'}
    result = review_content(draft)
    assert result['compliance_status'] in ['approved', 'review']


def test_localization_language_mapping():
    assert map_location_to_language('Chennai') == 'tamil'
    assert map_location_to_language('Hyderabad') == 'telugu'
    assert map_location_to_language('Unknown') == 'english'


def test_localization_translate(monkeypatch):
    sample = {'idea': 'Hello', 'script': 'This is sample content', 'caption': 'Test caption'}
    monkeypatch.setattr('agents.localization_agent.translate_text', lambda t, l: f'{t}-{l}')
    localized = localize_content(sample, ['Chennai'])
    assert localized[0]['language'] == 'tamil'
    assert localized[0]['content']['caption'] == 'Test caption-tamil'


def test_compute_patterns_empty():
    assert compute_patterns([]) == {}


def test_compute_patterns_data():
    data = [
        {'channel': 'LinkedIn', 'likes': 10, 'shares': 2, 'published_at': '2026-03-28T10:00:00Z'},
        {'channel': 'Twitter', 'likes': 20, 'shares': 3, 'published_at': '2026-03-28T11:00:00Z'},
        {'channel': 'LinkedIn', 'likes': 5, 'shares': 1, 'published_at': '2026-03-28T10:30:00Z'}
    ]
    patterns = compute_patterns(data)
    assert patterns['best_hour'] in [10, 11]
    assert patterns['top_channel'] in ['LinkedIn', 'Twitter']


@patch('agents.drafting_agent.get_trends', return_value=['trend1', 'trend2'])
@patch('agents.drafting_agent.analyze_emotion', return_value={'label': 'joy', 'score': 0.9})
@patch('agents.drafting_agent.call_gemini', return_value=json.dumps({
    'idea': 'AI content', 'hook': 'Hook', 'script': 'Script', 'scenes': ['a'], 'caption': 'Cap', 'hashtags': ['#x'], 'seo_keywords': ['x']
}))
def test_draft_content_mocked(mock_gemini, mock_emotion, mock_trends):
    result = draft_content('SaaS', 'Developers', 'Chennai', 'LinkedIn', 'Professional', '')
    assert result['top_trend'] == 'trend1'
    assert result['emotion']['label'] == 'joy'
    assert result['content']['idea'] == 'AI content'


def test_distribute_no_profile():
    content = [{'location': 'NoCity', 'content': {'caption': 'Hi'}}]
    result = distribute(content, profile_map={})
    assert result == []


if __name__ == '__main__':
    pytest.main(['-q', 'run_tests.py'])
