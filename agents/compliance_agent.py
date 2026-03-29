import json
import re
from config import BRAND_RULES_FILE


def load_brand_rules(path: str = BRAND_RULES_FILE):
    rules = {'prohibited': [], 'required': []}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.lower().startswith('prohibited:'):
                    rules['prohibited'] = [w.strip().lower() for w in line.split(':', 1)[1].split(',') if w.strip()]
                if line.lower().startswith('required:'):
                    rules['required'] = [p.strip() for p in line.split(':', 1)[1].split('.,') if p.strip()]
    except FileNotFoundError:
        pass
    return rules


def check_text(text: str, rules):
    violations = []
    suggestions = []
    lower = text.lower() if isinstance(text, str) else ''
    for bad in rules.get('prohibited', []):
        if bad and bad in lower:
            violations.append(bad)
            suggestions.append(f'Remove or replace "{bad}"')
    required = rules.get('required', [])
    for req in required:
        if req and req.lower() not in lower:
            suggestions.append(f'Add required disclaimer: {req}')
    return violations, suggestions


def review_content(draft_json: dict):
    rules = load_brand_rules()
    report = {'compliance_status': 'approved', 'issues': []}

    text_fields = ['idea', 'hook', 'script', 'caption']
    for field in text_fields:
        value = draft_json.get(field, '')
        hypocrisy, suggestion = check_text(value, rules)
        if hypocrisy:
            report['compliance_status'] = 'review'
            report['issues'].append({'field': field, 'violations': hypocrisy, 'suggestions': suggestion})

    if report['compliance_status'] != 'approved' and not report['issues']:
        report['compliance_status'] = 'approved'

    report['summary'] = 'Manual check required' if report['compliance_status'] == 'review' else 'No issues found'
    return report
