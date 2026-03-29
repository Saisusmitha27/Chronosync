from agents.drafting_agent import get_stock_video_url
samples = [
    'business office working',
    'team collaboration',
    'person using laptop',
    'startup workspace',
    'technology workspace'
]

print('Checking Pexels for each visual query:')
for v in samples:
    url = get_stock_video_url(v)
    print(f"- {v}: {'FOUND' if url else 'NOT FOUND'}")
    if url:
        print('  URL:', url)
