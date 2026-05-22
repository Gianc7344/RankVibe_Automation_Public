# -*- coding: utf-8 -*-
"""
OpenRouter ucretSize model testi - hangi modeller su an gercekten calisiyor?
"""
import sys
import httpx

# Windows konsolunda encoding sorununu onle
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import os
from pathlib import Path

def _load_env_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("OPENROUTER_API_KEY="):
                        val = line.split("=", 1)[1].strip()
                        if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                            val = val[1:-1]
                        return val
        except Exception:
            pass
    return "YOUR_OPENROUTER_API_KEY_HERE"

API_KEY = _load_env_key()

print("Ucretiz modeller aliniyor...")
r = httpx.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=30
)
all_models = r.json().get("data", [])

free_models = []
for m in all_models:
    pricing = m.get("pricing", {})
    if str(pricing.get("prompt", "1")) == "0":
        free_models.append(m["id"])

print(f"\n=== TOPLAM UCRETSIZ MODEL: {len(free_models)} ===")
for mid in free_models:
    print(f"  {mid}")

# Mevcut liste
CURRENT_MODELS = [
    "qwen/qwen3-8b:free",
    "google/gemma-2-9b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
]

# Tum ucretsiz modelleri test et (mevcut + yeni)
all_to_test = list(dict.fromkeys(CURRENT_MODELS + free_models))  # sirali, tekrarsiz

print(f"\n=== CANLI TEST ({len(all_to_test)} model) ===")
working = []
for mid in all_to_test:
    tag = "[LISTEDE]" if mid in CURRENT_MODELS else "[YENI]   "
    try:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": mid,
                "messages": [{"role": "user", "content": "Say OK"}],
            },
            timeout=15
        )
        if resp.status_code == 200:
            print(f"  OK   {tag}: {mid}")
            working.append(mid)
        else:
            print(f"  FAIL {tag} ({resp.status_code}): {mid}")
    except Exception as e:
        print(f"  ERR  {tag}: {mid} - {type(e).__name__}")

print(f"\n=== SONUC: {len(working)} model calisiyor ===")
for m in working:
    print(f"  -> {m}")
