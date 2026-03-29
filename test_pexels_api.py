import os
import config  # Load environment variables
from agents.drafting_agent import query_pexels_video

print("🔍 Testing Pexels API call...")

# Test with a simple query
query = "business office"
print(f"Querying Pexels for: '{query}'")

url = query_pexels_video(query)
if url:
    print(f"✅ SUCCESS: Found video URL: {url[:80]}...")
else:
    print("❌ FAILED: No video found")

print("\n🏁 API test complete!")