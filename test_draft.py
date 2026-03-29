import os
import json
os.environ['IMAGEMAGICK_BINARY'] = r'C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe'

# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

from agents.drafting_agent import draft_content

print("Testing draft_content...")
result = draft_content(
    niche="SaaS",
    audience="Developers",
    location="Chennai", 
    platform="LinkedIn",
    tone="Professional",
    internal_data=""
)

print("\n✅ Draft result:")
print(f"Content keys: {list(result['content'].keys())}")
scenes = result['content'].get('scenes', [])
print(f"Number of scenes: {len(scenes)}")

for i, scene in enumerate(scenes):
    print(f"\nScene {i+1}:")
    print(f"  text_overlay: {scene.get('text_overlay')}")
    print(f"  visual: {scene.get('visual')}")
    media_url = scene.get('media_url')
    if media_url:
        print(f"  ✅ media_url: {media_url[:70]}...")
    else:
        print(f"  ❌ media_url: NOT SET")
