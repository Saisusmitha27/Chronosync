import os
from agents.drafting_agent import query_pexels_video, get_stock_video_url

# Test Pexels API directly
print("🔍 Testing Pexels API integration...")
print(f"PEXELS_API_KEY set: {bool(os.getenv('PEXELS_API_KEY'))}")

# Test with concrete visual descriptions
test_queries = [
    "business office working",
    "person using laptop in office",
    "team collaboration meeting",
    "person frustrated at computer"
]

print("\n📹 Testing individual queries:")
for query in test_queries:
    print(f"\n  Query: '{query}'")
    url = query_pexels_video(query)
    if url:
        print(f"  ✅ Found: {url[:60]}...")
    else:
        print("  ❌ No video found")

print("\n🎬 Testing get_stock_video_url function:")
for query in test_queries:
    print(f"\n  Query: '{query}'")
    url = get_stock_video_url(query)
    if url:
        print(f"  ✅ Found: {url[:60]}...")
    else:
        print("  ❌ No video found")

print("\n🏁 Test complete!")