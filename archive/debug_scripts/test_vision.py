import os
import httpx
import base64
import json
from app import VISION_ONLY_MODELS, API_KEY, _fuzzy_parse_json, CLIP_DIR, _sanitize_label

def test_vision():
    clip_path = list(CLIP_DIR.glob("*.mp4"))[0]
    frame_path = CLIP_DIR / "test_frame.jpg"
    
    # We already extracted test_frame.jpg in the previous run, let's make sure it's there
    if not frame_path.exists():
        from app import _extract_frame
        _extract_frame(clip_path, frame_path)

    prompt = (
        "You are the creative AI behind the RankVibe YouTube channel.\n"
        "Look at this image carefully.\n"
        "Analyze the image and tell me the X-Axis offset of the MAIN EVENT/SUBJECT.\n"
        "Return ONLY valid JSON, no markdown:\n"
        "{\n"
        "  \"description\": \"<text>\",\n"
        "  \"x_offset\": 0\n"
        "}\n"
    )

    with open(frame_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    for model in VISION_ONLY_MODELS:
        print(f"\nTrying model: {model}")
        try:
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}]},
                timeout=40
            )
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                print(f"Raw response: {raw}")
                result = _fuzzy_parse_json(raw)
                print(f"Parsed JSON: {result}")
                if result and "description" in result:
                    print("SUCCESS!")
                    return
            else:
                print(f"Error body: {resp.text}")
        except Exception as e:
            print(f"Exception: {e}")

test_vision()
