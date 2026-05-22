import httpx
import json

resp = httpx.get("https://openrouter.ai/api/v1/models")
models = resp.json()["data"]

free_vision_models = []
for m in models:
    if m["pricing"]["prompt"] == "0" and m["pricing"]["completion"] == "0":
        if "architecture" in m and "modality" in m["architecture"]:
            if "image" in m["architecture"]["modality"]:
                free_vision_models.append(m["id"])

print("Free Vision Models:")
for m in free_vision_models:
    print(m)
