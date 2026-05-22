import os
from pathlib import Path
from app import _extract_frame, CLIP_DIR

# Get the first .mp4 file in CLIP_DIR
clips = list(CLIP_DIR.glob("*.mp4"))
if not clips:
    print("No clips found in", CLIP_DIR)
else:
    clip_path = clips[0]
    out_path = CLIP_DIR / "test_frame.jpg"
    print(f"Testing extraction on {clip_path.name}...")
    success = _extract_frame(clip_path, out_path)
    print(f"Extraction success: {success}")
    if out_path.exists():
        print("Frame created successfully.")
        out_path.unlink()
    else:
        print("Frame was not created.")
