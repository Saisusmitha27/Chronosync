"""
One-time script to generate fallback assets for Metacortex video pipeline.
Creates:
  - assets/default.mp4  : 10-second animated gradient video (720x1280)
  - assets/music.mp3    : 30-second silent audio placeholder
"""

import os
import struct
import wave
import numpy as np

os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def create_default_video():
    """Create a 10-second animated gradient video using MoviePy + numpy."""
    from moviepy.editor import VideoClip

    W, H = 720, 1280
    DURATION = 10
    FPS = 24

    def make_frame(t):
        """Generate a dark blue-to-teal animated gradient frame."""
        progress = t / DURATION
        frame = np.zeros((H, W, 3), dtype=np.uint8)

        for y in range(H):
            ratio = y / H
            # Animate: shift the gradient over time
            shifted = (ratio + progress * 0.5) % 1.0

            r = int(15 + 25 * shifted)
            g = int(30 + 60 * shifted)
            b = int(60 + 80 * (1 - shifted))

            frame[y, :, 0] = r
            frame[y, :, 1] = g
            frame[y, :, 2] = b

        return frame

    clip = VideoClip(make_frame, duration=DURATION)
    output_path = os.path.join(ASSETS_DIR, "default.mp4")
    clip.write_videofile(output_path, fps=FPS, codec="libx264", audio=False)
    clip.close()
    print(f"[OK] Created {output_path}")
    return output_path


def create_silent_music():
    """Create a 30-second silent WAV then convert if possible, else keep WAV."""
    duration_sec = 30
    sample_rate = 44100
    num_samples = duration_sec * sample_rate

    wav_path = os.path.join(ASSETS_DIR, "music.wav")
    mp3_path = os.path.join(ASSETS_DIR, "music.mp3")

    # Write silent WAV
    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        silent_data = b"\x00\x00" * num_samples
        wf.writeframes(silent_data)

    # Try converting to MP3 using moviepy/ffmpeg
    try:
        from moviepy.editor import AudioFileClip
        audio = AudioFileClip(wav_path)
        audio.write_audiofile(mp3_path)
        audio.close()
        os.remove(wav_path)
        print(f"[OK] Created {mp3_path}")
        return mp3_path
    except Exception as e:
        print(f"[WARN] MP3 conversion failed ({e}), keeping WAV")
        # Rename wav to mp3 path for compatibility (ffmpeg can still read it)
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
        os.rename(wav_path, mp3_path)
        print(f"✅ Created {mp3_path} (WAV format)")
        return mp3_path


if __name__ == "__main__":
    os.makedirs(ASSETS_DIR, exist_ok=True)
    print("Creating fallback assets...")
    create_default_video()
    create_silent_music()
    print("\n[DONE] All assets created in ./assets/")
