import os
import config  # Load environment variables
print("🔍 Checking Pexels API setup...")

# Check if API key is set
api_key = os.getenv('PEXELS_API_KEY')
if api_key:
    print(f"✅ PEXELS_API_KEY is set: {api_key[:10]}...")
else:
    print("❌ PEXELS_API_KEY not found in environment")

# Quick test import
try:
    from agents.drafting_agent import query_pexels_video
    print("✅ query_pexels_video function imported successfully")
except ImportError as e:
    print(f"❌ Import failed: {e}")

print("\n🏁 Basic setup check complete!")