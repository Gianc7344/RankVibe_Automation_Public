"""
RankVibe Automation — Flask Backend
Sahne kesim (main.py) ve ranking video oluşturma (taslak.py) scriptlerini
web arayüzünden kontrol eder.  SSE ile canlı terminal çıktısı stream eder.
"""

import os
import sys
import re
import json
import shutil
import subprocess
import threading
import queue
import time
import traceback
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify, Response,
    send_from_directory
)

# ── Paths ──────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
CLIP_DIR   = BASE_DIR / "clips"
THUMB_DIR  = BASE_DIR / "thumbnails"
FINAL_DIR  = BASE_DIR / "final_videolar"
DATA_DIR   = BASE_DIR / "data"
FAV_FILE       = DATA_DIR / "favorites.json"
PROFILES_FILE  = DATA_DIR / "profiles.json"
HISTORY_FILE   = DATA_DIR / "history.json"
VENV_PY        = BASE_DIR / "venv" / "Scripts" / "python.exe"

# ── API Keys & Models ──────────────────────────────────────
def _load_env_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = BASE_DIR / ".env"
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
# Nisan 2026 itibarıyla OpenRouter'da aktif ücretsiz modeller.
# Sistem bu listeyi sırasıyla dener; bir model hata verirse bir sonrakine geçer.
VISION_MODELS = [
    # --- Text-only modeller (fikir üretme, arama tavsiyesi) ---
    "meta-llama/llama-3.3-70b-instruct:free",          # Llama 3.3 70B
    "google/gemma-3-27b-it:free",                      # Gemma 3 27B
    "openai/gpt-oss-20b:free",                         # OpenAI OSS 20B
    "nvidia/nemotron-3-super-120b-a12b:free",          # Nemotron 120B
    "google/gemma-3-12b-it:free",                      # Gemma 3 12B
    "nousresearch/hermes-3-llama-3.1-405b:free",       # Hermes 3 405B
    "google/gemma-3-4b-it:free",                       # Gemma 3 4B
    "meta-llama/llama-3.2-3b-instruct:free",           # Llama 3.2 3B
]

# Görsel analiz (image input) için sadece vision-capable modeller
# Bu modeller hem metin hem de base64 image içeren istekleri işleyebilir
VISION_ONLY_MODELS = [
    "google/gemma-4-31b-it:free",                      # Gemma 4 31B Vision ✅
    "google/gemma-4-26b-a4b-it:free",                  # Gemma 4 26B Vision ✅
    "nvidia/nemotron-nano-12b-v2-vl:free",             # Nemotron Nano VL ✅
    "google/lyria-3-pro-preview",                      # Lyria Pro ✅
    "openrouter/free",                                 # Fallback router
]

app = Flask(__name__)

# ── DIAGNOSTIC: Global hata yakalayıcılar ─────────────────
# Sessiz kalan her route exception'ı terminale düşer
@app.errorhandler(Exception)
def _handle_any_exception(exc):
    print(f"\n{'='*60}")
    print(f"[FLASK GLOBAL ERROR] {type(exc).__name__}: {exc}")
    traceback.print_exc()
    print('='*60)
    return jsonify({"error": f"Sunucu hatası: {type(exc).__name__}: {exc}"}), 500

# ── FFmpeg Startup Check ──────────────────────────────────
def _check_ffmpeg():
    """Uygulama başlarken FFmpeg'in mevcut olduğunu doğrular."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"✅ FFmpeg bulundu: {ffmpeg_path}")
        return ffmpeg_path
    # Sabit yol dene (Windows)
    fallback = r"C:\ffmpeg\bin\ffmpeg.exe"
    if Path(fallback).exists():
        print(f"✅ FFmpeg bulundu (sabit yol): {fallback}")
        return fallback
    print("❌ KRİTİK: FFmpeg sisteminizde bulunamadı!")
    print("   Lütfen FFmpeg'i kurun: https://ffmpeg.org/download.html")
    print("   ve PATH ortam değişkenine ekleyin.")
    return None

FFMPEG_AVAILABLE = _check_ffmpeg()

# ── SSE helpers ────────────────────────────────────────────
_log_queues: dict[str, queue.Queue] = {}
_running: dict[str, bool] = {}
# PATCH: Process referansları — cancel ve watchdog için
_processes: dict[str, subprocess.Popen] = {}
# PATCH: Her job için max çalışma süresi (saniye)
_JOB_HARD_TIMEOUT = 1800  # 30 dakika


# ── JSON Dosya Güvenliği ───────────────────────────────────
def _safe_read_json(filepath: Path, default=None):
    """
    JSON dosyasını güvenli şekilde okur.
    Bozuk dosya tespit edilirse yedek (.bak) alıp None döndürür.
    """
    if default is None:
        default = []
    if not filepath.exists():
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default
            return json.loads(content)
    except json.JSONDecodeError as e:
        # Dosya bozuk → zaman damgalı yedek al ve sıfırlama yapmadan None dön
        bak_path = filepath.with_suffix(f".{int(time.time())}.json.bak")
        try:
            shutil.copy2(str(filepath), str(bak_path))
            print(f"⚠️ {filepath.name} bozuk! Yedek alındı → {bak_path.name}")
        except Exception:
            pass
        print(f"⚠️ JSON parse hatası ({filepath.name}): {e}. Güvenlik sebebiyle None döndürülüyor.")
        return None
    except (FileNotFoundError, PermissionError) as e:
        print(f"⚠️ {filepath.name} okunamadı: {e}")
        return default
    except Exception as e:
        print(f"❌ {filepath.name} yükleme hatası: {e}")
        return default


def _safe_write_json(filepath: Path, data):
    """
    JSON dosyasını güvenli şekilde yazar.
    Yazma sırasında hata olursa dosyayı bozmaz (temp dosya stratejisi).
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = filepath.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Temp dosya başarılı yazıldıysa asıl dosyanın üzerine taşı
        shutil.move(str(tmp_path), str(filepath))
    except Exception as e:
        print(f"❌ {filepath.name} yazma hatası: {e}")
        # Temp dosyayı temizle
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _load_favorites():
    return _safe_read_json(FAV_FILE, default=[])

def _save_favorites(favs):
    _safe_write_json(FAV_FILE, favs)

def _load_profiles():
    return _safe_read_json(PROFILES_FILE, default={})

def _save_profiles(profiles):
    _safe_write_json(PROFILES_FILE, profiles)


def _load_history() -> list:
    """Son üretilen 20 fikir/etiket geçmişini yükler."""
    data = _safe_read_json(HISTORY_FILE, default=[])
    if data is None or not isinstance(data, list):
        return []
    return data

def _save_history(history: list):
    """Geçmişi history.json'a kaydeder; maksimum 20 kayıt saklar."""
    _safe_write_json(HISTORY_FILE, history[-20:])


def _stream_process(cmd: list[str], job_id: str):
    """
    Subprocess çalıştır, stdout/stderr'i satır satır kuyruğa ekle.
    PATCH:
      - proc referansı _processes'e kaydediliyor (cancel desteği için)
      - Watchdog thread: _JOB_HARD_TIMEOUT sonunda process kill edilir
    """
    q = _log_queues[job_id]
    _running[job_id] = True
    proc = None
    try:
        import os
        SYSTEM_FFMPEG = shutil.which("ffmpeg")
        FFMPEG_EXE = SYSTEM_FFMPEG if SYSTEM_FFMPEG else r"C:\ffmpeg\bin\ffmpeg.exe"
        if not Path(FFMPEG_EXE).exists() and not SYSTEM_FFMPEG:
            q.put(f"❌ KRİTİK HATA: FFmpeg bulunamadı! Yol: {FFMPEG_EXE}")
            q.put("__EXIT_CODE:1")
            return

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,   # DIAGNOSTIC: stderr ayrı yakalanıyor
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(BASE_DIR),
            env=env
        )
        _processes[job_id] = proc

        # PATCH: Watchdog — süre aşımında process'i zorla kapat
        def _watchdog_kill():
            try:
                alive = proc.wait(timeout=_JOB_HARD_TIMEOUT)
            except subprocess.TimeoutExpired:
                print(f"⚠️  Job {job_id} hard timeout ({_JOB_HARD_TIMEOUT}s). Killing...")
                proc.kill()
                q.put(f"⏱️ İşlem {_JOB_HARD_TIMEOUT // 60} dakikada tamamlanamadı, otomatik durduruldu.")
                q.put("__EXIT_CODE:1")
        threading.Thread(target=_watchdog_kill, daemon=True).start()

        # DIAGNOSTIC: stderr'i ayrı thread'de oku ve hem logla hem kuyruğa ekle
        def _drain_stderr():
            try:
                for line in proc.stderr:
                    line = line.rstrip("\n")
                    if line:
                        print(f"[subprocess STDERR] {line}")
                        # Gerçek hataları SSE üzerinden de ilet
                        if any(kw in line.lower() for kw in ["error", "traceback", "exception", "critical", "fatal"]):
                            q.put(f"⚠️ [STDERR] {line}")
            except Exception:
                pass
        threading.Thread(target=_drain_stderr, daemon=True).start()

        for line in proc.stdout:               # type: ignore[union-attr]
            q.put(line.rstrip("\n"))
        proc.wait()
        q.put(f"__EXIT_CODE:{proc.returncode}")
    except Exception as exc:
        q.put(f"HATA: {exc}")
        q.put("__EXIT_CODE:1")
    finally:
        _running[job_id] = False
        _processes.pop(job_id, None)


def _sse_generator(job_id: str):
    q = _log_queues.setdefault(job_id, queue.Queue())
    # PATCH: SSE'nin sonsuz beklememesi için maksimum süre
    deadline = time.time() + _JOB_HARD_TIMEOUT + 30
    while True:
        if time.time() > deadline:
            yield f"data: {json.dumps({'type':'done','code':1,'reason':'sse_timeout'})}\n\n"
            _log_queues.pop(job_id, None)
            _running.pop(job_id, None)
            break
        try:
            msg = q.get(timeout=1)
        except queue.Empty:
            # keep-alive
            yield ":\n\n"
            if not _running.get(job_id, False) and q.empty():
                yield f"data: {json.dumps({'type':'done'})}\n\n"
                _log_queues.pop(job_id, None)
                _running.pop(job_id, None)
                break
            continue

        if msg.startswith("__EXIT_CODE:"):
            code = int(msg.split(":")[1])
            yield f"data: {json.dumps({'type':'done','code':code})}\n\n"
            _log_queues.pop(job_id, None)
            _running.pop(job_id, None)
            break
        else:
            yield f"data: {json.dumps({'type':'log','text':msg})}\n\n"


# ── Fuzzy JSON Parser (LLM yanıtları için) ─────────────────
def _fuzzy_parse_json(raw_text: str):
    """
    LLM'den gelen metni JSON'a parse eder.
    Strateji:
      1. Markdown fence'lerini temizle (```json ... ```)
      2. Direkt json.loads dene
      3. Regex ile ilk {...} bloğunu bul
      4. Trailing comma gibi yaygın hataları düzelt ve tekrar dene
    Başarısızsa None döner.
    """
    if not raw_text or not raw_text.strip():
        return None

    text = raw_text.strip()

    # 1) Markdown fence temizliği
    text = re.sub(r"```(?:json)?\s*", "", text).strip()

    # 2) Direkt parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3) Regex ile { ... } bloğunu bul (en dıştaki süslü parantezler)
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        json_candidate = match.group(0)
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            # 4) Trailing comma düzelt  (", }" → " }")
            fixed = re.sub(r",\s*([}\]])", r"\1", json_candidate)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    # 5) Basit { } arama (fallback)
    s, e = text.find("{"), text.rfind("}") + 1
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e])
        except json.JSONDecodeError:
            fixed = re.sub(r",\s*([}\]])", r"\1", text[s:e])
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    return None


# ── Routes ─────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/favorites", methods=["GET"])
def get_favorites():
    favs = _load_favorites()
    return jsonify(favs if favs is not None else [])

@app.route("/api/toggle-favorite", methods=["POST"])
def toggle_favorite():
    data = request.get_json(force=True)
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Eksik parametre"}), 400
    favs = _load_favorites()
    if favs is None:
        favs = []
    if filename in favs:
        favs.remove(filename)
    else:
        favs.append(filename)
    _save_favorites(favs)
    return jsonify({"success": True, "favorites": favs})


@app.route("/api/clips")
def list_clips():
    """clips/ klasöründeki tüm klipleri listele."""
    clips = []
    if CLIP_DIR.exists():
        for f in sorted(CLIP_DIR.iterdir()):
            if f.suffix.lower() == ".mp4":
                thumb_name = f.stem + ".jpg"
                thumb_exists = (THUMB_DIR / thumb_name).exists()
                clips.append({
                    "filename": f.name,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    "thumbnail": thumb_name if thumb_exists else None,
                })
    return jsonify(clips)


def _sanitize_search_terms(result_json: dict) -> dict:
    """
    AI'dan gelen search_terms listesini doğrular ve temizler.
    - | veya newline ile birleştirilmiş stringleri ayırır
    - Her terimi negatif operatörlerden temizler (yt-dlp bunları desteklemez)
    - Boş veya çok kısa terimleri atar
    - Minimum 3, maksimum 5 terim döndürür
    """
    terms = result_json.get("search_terms", [])

    # String ise böl
    if isinstance(terms, str):
        # | veya newline ile ayrılmış olabilir
        terms = re.split(r"[|\n]", terms)

    clean_terms = []
    for t in terms:
        t = str(t).strip()
        if not t:
            continue
        # Negatif operatörleri temizle: -gameplay -gta vb. (yt-dlp bunları parse etmez)
        t = re.sub(r"\s+-\w+", "", t).strip()
        if len(t) > 5:
            clean_terms.append(t)

    # Yeterli terim yoksa fallback ekle
    if len(clean_terms) < 1:
        clean_terms = [
            "funny fails compilation caught on camera",
            "epic fails real life compilation",
            "people fails caught on camera funny moments"
        ]

    result_json["search_terms"] = clean_terms[:5]
    return result_json


@app.route("/api/generate-idea", methods=["POST"])
def generate_idea():
    """Analiz metnini (veya görseli) alıp yeni video fikri ve arama terimi üretir."""
    data = request.get_json(force=True)
    analytics = data.get("analytics", "").strip()
    channel_rules = data.get("channel_rules", "").strip()
    target_audience = data.get("target_audience", "").strip()
    target_age = data.get("target_age", "").strip()
    image_data = data.get("image_data") # "data:image/jpeg;base64,..."
    previous_ideas = data.get("previous_ideas", [])
    
    if not analytics and not image_data and not channel_rules:
        return jsonify({"error": "Analiz metni veya görseli gerekli"}), 400

    prompt = (
        "You are the AI behind the RankVibe YouTube channel.\n"
        "Your goal is to suggest ONE new In-Real-Life (IRL) COMPILATION video idea.\n\n"

        "=== 🚨 HYBRID LANGUAGE RULE (READ CAREFULLY) ===\n"
        "This output has TWO sections with DIFFERENT language requirements:\n"
        "  ① TURKISH fields  → 'title_tr' and 'description_tr'  MUST be written in TURKISH.\n"
        "  ② ENGLISH fields  → 'search_terms' and 'clip_labels' MUST be written in ENGLISH.\n"
        "Mixing languages within a field is FORBIDDEN.\n\n"

        "=== STEP 1: CHOOSE A CONCEPT ===\n"
        "Pick a theme about real-life human/animal/vehicle moments that can be ranked #1-#5.\n"
        "Examples: sports bloopers, construction fails, kitchen accidents, close calls, funny animal moments, near misses.\n"
        "FORBIDDEN: car crashes, fatal accidents, violence, news, movies, video games, gameplay, esports, animations, CGI, Twitch streams, simulations.\n\n"

        "=== STEP 2: WRITE THE TURKISH UI FIELDS ===\n"
        "  'title_tr'       — Short, punchy video title written in TURKISH. ALL CAPS. Max 6 words.\n"
        "                     Example: 'MUTFAKTA YAŞANAN DESTANSÎ SAKARLIKLAR'\n"
        "  'description_tr' — One Turkish sentence describing the video. Max 15 words.\n"
        "                     Example: 'Profesyonel şeflerin mutfakta yaşadığı en komik kazalar bir arada!'\n\n"

        "=== STEP 3: CREATE ENGLISH SEARCH TERMS ===\n"
        "Think: 'What would someone type on YouTube to find a COMPILATION of these real events?'\n"
        "Rules for each search term:\n"
        "  - Must contain the core topic (e.g. 'kitchen bloopers', 'soccer fails')\n"
        "  - Use 1-2 generic boosters ONLY if they fit (compilation, caught on camera, real life), but PRIORITIZE the specific topic words.\n"
        "  - MUST BE STRICTLY IN ENGLISH. No Turkish or other non-English words.\n"
        "  - Must NOT contain: game names (minecraft, gta, skate, roblox), 'gameplay', 'stream', 'twitch'\n"
        "  - Must NOT use '|' character — each term is a separate array element\n"
        "  - Must NOT include '-word' negative filters (we handle them automatically).\n"
        "  - Should be 3-8 words long\n\n"

        "GOOD search term examples:\n"
        "  'kitchen disaster fails caught on camera'\n"
        "  'chef mishaps funny moments compilation'\n"
        "  'construction worker accidents real life'\n\n"

        "BAD search term examples (NEVER use these patterns):\n"
        "  'soccer fails IRL -gameplay -gta'  ← has negative filter, forbidden\n"
        "  'funny moments | real life fails'   ← has | separator, forbidden\n"
        "  'minecraft fails compilation'       ← has game name, forbidden\n\n"

        "=== STEP 4: CREATE ENGLISH CLIP LABELS ===\n"
        "'clip_labels' are the creative on-screen overlay texts shown on each ranked clip.\n"
        "RankVibe treats real-world events as glitches in a simulation — cold, technical, darkly funny.\n"
        "Rules:\n"
        "  - MUST be in ENGLISH only. No Turkish words.\n"
        "  - Exactly 5 labels, one per rank (#5 down to #1).\n"
        "  - Each label: 3 to 5 words. Creative and punchy.\n"
        "  - Prioritize vocabulary from: Glitch, Error, Physics, Fail, Logic, Matrix, Bug, Gravity, Exploit, Anomaly, Defect, Override, Collision, Simulation.\n"
        "  - DO NOT use plain literal descriptions (e.g. 'Kitchen Fail' or 'Chef Spills'). Make them feel like error codes or game events.\n"
        "  - No emojis, no punctuation.\n"
        "  BAD  examples: ['Kitchen Fail', 'Chef Disaster', 'Cooking Blooper', 'Epic Spill', 'Total Meltdown']\n"
        "  GOOD examples: ['Gravity Override Detected', 'Physics Error Cooking', 'Logic Anomaly Kitchen', 'Simulation Bug Chef', 'Unexpected Meltdown Glitch']\n\n"
    )

    if channel_rules:
        prompt += (
            "=== CHANNEL RULES (MUST FOLLOW) ===\n"
            f"{channel_rules}\n\n"
        )

    if target_audience or target_age:
        prompt += "=== TARGET AUDIENCE ===\n"
        if target_audience:
            prompt += f"Audience type: {target_audience}\n"
        if target_age:
            prompt += f"Age range: {target_age}\n"
        prompt += "\n"

    if previous_ideas:
        prompt += "=== ALREADY SUGGESTED (DO NOT REPEAT) ===\n"
        for prev in previous_ideas:
            prompt += f"- {prev}\n"
        prompt += "\n"

    # --- Diversity filter: inject recent history ---
    history = _load_history()
    if history:
        prompt += (
            "=== DIVERSITY FILTER — RECENT HISTORY (LAST 20 IDEAS) ===\n"
            "The system has ALREADY produced ideas/labels with these themes recently.\n"
            "You MUST approach the topic from a completely DIFFERENT angle, category, or perspective.\n"
            "Do NOT reuse the same sports, locations, or activity types listed below:\n"
        )
        for entry in history[-20:]:
            prompt += f"- {entry}\n"
        prompt += "\n"

    if analytics:
        prompt += f"=== LAST VIDEO ANALYTICS ===\n{analytics}\n\n"

    prompt += (
        "=== OUTPUT FORMAT ===\n"
        "Return ONLY valid JSON. No markdown, no explanation, no extra text.\n"
        "{\n"
        "  \"title_tr\": \"TÜRKÇE BAŞLIK BURADA (ALL CAPS, max 6 kelime)\",\n"
        "  \"description_tr\": \"Türkçe açıklama cümlesi burada. Maks 15 kelime.\",\n"
        "  \"search_terms\": [\n"
        "    \"first English search phrase\",\n"
        "    \"second English search phrase\",\n"
        "    \"third English search phrase\"\n"
        "  ],\n"
        "  \"clip_labels\": [\"English Label 1\", \"English Label 2\", \"English Label 3\", \"English Label 4\", \"English Label 5\"]\n"
        "}\n"
        "❗ FINAL CHECK:\n"
        "  - 'title_tr' and 'description_tr' → Turkish only. If any English word slips in, rewrite in Turkish.\n"
        "  - 'search_terms' and 'clip_labels' → English only. If any Turkish word slips in, rewrite in English.\n"
    )

    message_content = [{"type": "text", "text": prompt}]
    if image_data:
        message_content.append({
            "type": "image_url",
            "image_url": {"url": image_data}
        })

    # Kullanıcıya gösterilecek Temiz Türkçe hata mesajı
    _USER_FRIENDLY_ERROR = (
        "Yapay zeka sunucuları şu an çok yoğun. "
        "Lütfen 30 saniye bekleyip tekrar deneyin."
    )

    try:
        import httpx

        last_error = ""
        models = list(VISION_MODELS)  # kopya al – orijinali değiştirme
        for i, model in enumerate(models, start=1):
            print(f"[generate-idea] Model {i}/{len(models)} deneniyor: {model}")
            try:
                resp = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": message_content}],
                    },
                    timeout=20,  # PATCH: 60s → 20s — yavaş model sonraki modele bırakır
                )
            except Exception as req_exc:
                last_error = f"Bağlantı hatası ({model}): {req_exc}"
                print(f"[generate-idea] ⚠ {last_error}")
                continue  # ağ hatası → sonraki modele geç

            if resp.status_code == 200:
                try:
                    result_text = resp.json()["choices"][0]["message"]["content"]
                except Exception:
                    last_error = f"Yanıt parse hatası ({model})"
                    print(f"[generate-idea] ⚠ {last_error}")
                    continue
                result_json = _fuzzy_parse_json(result_text)
                if result_json is None:
                    last_error = f"Geçersiz JSON ({model})"
                    print(f"[generate-idea] ⚠ {last_error}")
                    continue
                print(f"[generate-idea] ✅ Başarılı: {model}")
                result_json = _sanitize_search_terms(result_json)
                # --- Save to diversity history ---
                try:
                    history = _load_history()
                    title = result_json.get("title_tr", "")
                    labels = result_json.get("clip_labels", [])
                    new_entries = [title] + (labels if isinstance(labels, list) else [])
                    history.extend([e for e in new_entries if e])
                    _save_history(history)
                except Exception as hist_err:
                    print(f"[generate-idea] ⚠ Geçmiş kaydedilemedi: {hist_err}")
                return jsonify(result_json)

            else:
                # 429, 404, 500, 502, 503, 528 ve diğer TÜM hatalar → sessizce atla
                last_error = f"HTTP {resp.status_code} ({model})"
                print(f"[generate-idea] ✗ {last_error} – sonraki modele geçiliyor")
                if resp.status_code == 429:
                    time.sleep(1)  # rate-limit için kısa bekleme
                continue

        # Tüm modeller tükendi – kullanıcıya temiz Türkçe hata göster
        print(f"[generate-idea] ❌ Tüm modeller başarısız. Son hata: {last_error}")
        return jsonify({"error": _USER_FRIENDLY_ERROR}), 503

    except Exception as e:
        print(f"[generate-idea] ❌ Beklenmeyen hata: {e}")
        return jsonify({"error": _USER_FRIENDLY_ERROR}), 503


@app.route("/api/search-youtube", methods=["POST"])
def search_youtube():
    """Verilen arama terimleri ile yt-dlp üzerinden YouTube'da IRL derleme videoları bulur."""
    try:
        return _search_youtube_impl()
    except Exception as e:
        import traceback
        import subprocess
        traceback.print_exc()
        if "timeout" in str(e).lower() or isinstance(e, subprocess.TimeoutExpired):
            return jsonify({"error": f"YouTube araması (yt-dlp) zaman aşımına uğradı. Detay: {str(e)}"}), 500
        return jsonify({"error": str(e)}), 500

def _search_youtube_impl():
    data = request.get_json(force=True)
    raw_terms = data.get("search_terms", "")
    
    # search_terms liste veya string olabilir
    if isinstance(raw_terms, list):
        term_list = [t.strip() for t in raw_terms if t.strip()]
    else:
        raw_str = raw_terms.strip()
        if not raw_str:
            return jsonify({"error": "Arama terimi gerekli"}), 400
        # | veya virgül veya newline ile ayrılmış olabilir
        term_list = [t.strip() for t in re.split(r"[|,\n]", raw_str) if t.strip()]
    
    # Her terimi negatif operatörlerden temizle (yt-dlp desteklemez)
    term_list = [re.sub(r"\s+-\w+", "", t).strip() for t in term_list]
    term_list = [t for t in term_list if len(t) > 5]

    if not term_list:
        return jsonify({"error": "Arama terimi gerekli"}), 400

    # --- Başlık bazlı KARA LİSTE ---
    TITLE_BLACKLIST = [
        "gameplay", "gaming", "gamer", "playthrough", "lets play", "let's play",
        "walkthrough", "speedrun", "twitch", "stream", "streamer", "streamed",
        "minecraft", "fortnite", "gta", "beamng", "roblox", "valorant",
        "warzone", "cod", "call of duty", "overwatch", "league of legends",
        "dota", "apex legends", "rocket league", "pubg", "fifa", "nba 2k",
        "cs:go", "csgo", "counter strike", "gmod", "garrys mod", "mm2", "bloxburg",
        "game dev", "game development", "unreal engine", "unity engine",
        "video game", "pc game", "console game", "mobile game",
        "trolling", "troll", "noob", "fling", "lagging", "lag switch", "hitbox",
        "ai generated", "ai video", "artificial intelligence animation",
        "animated", "cartoon", "anime", "cgi", "deepfake", "ai art",
        "text to video", "stable diffusion", "midjourney",
        "tutorial", "how to", "explained", "review", "unboxing",
        "subtitles", "with captions", "lyrics", "karaoke",
        "vlog", "mukbang", "asmr", "reaction", "podcast", "interview",
        "q&a", "q and a", "ama", "storytime",
        # Haber, film, tv (Yapay zeka negatif filtre kuralı yerine backendden engelleme)
        "news", "haber", "haberler", "movie", "film", "tv", "television", "haber merkezi",
        "broadcast", "cnn", "bbc", "fox", "msnbc", "reuters", "associated press",
        # Ek: oyun başlıkları içeren genel kelimeler
        "skate", "skater", "skating", "skate 4", "skate 3",
        "2k", "simulator", "sim ", " sim", "roblox", "minecraft", "fortnite",
        "gta", "grand theft auto", "fivem", "modded", "modding",
    ]

    # --- Başlık güçlendirici anahtar kelimeler ---
    TITLE_BOOST_KEYWORDS = [
        "fail", "fails", "compilation", "funny", "caught on camera",
        "bloopers", "accident", "epic", "people", "gone wrong",
        "real", "moments", "dashcam", "sports", "animals",
        "kids", "try not to laugh", "best of",
    ]

    # --- Tercih edilen kanallar ---
    PREFERRED_CHANNELS = [
        "failarmy", "jukinvideo", "america's funniest", "afv",
        "just for laughs", "viral hog", "viral", "storyful",
        "the best fails", "fail compilation", "epic fails",
    ]

    def is_acceptable(video):
        title = (video.get("title") or "").lower()
        channel = (video.get("channel") or "").lower()
        
        gaming_channels = ["letsplay", "gaming", "gamer", "plays", "minecraft", "fortnite"]
        for kw in gaming_channels:
            if kw in channel and "fail" not in channel:
                return False
        
        for kw in TITLE_BLACKLIST:
            if kw in title:
                return False
        return True

    def score_video(video, search_terms):
        title = (video.get("title") or "").lower()
        channel = (video.get("channel") or "").lower()
        score = 0
        
        # 1. Konu Bazlı Anahtar Kelime Eşleşmesi (En Önemli)
        # Arama terimlerinden jenerik olmayan kelimeleri ayıklıyoruz
        boosters = {b.lower() for b in TITLE_BOOST_KEYWORDS}
        stop_words = {
            "a", "an", "the", "in", "on", "at", "with", "by", "for", "and", "or", "of", 
            "to", "from", "best", "top", "funny", "epic", "compilation", "caught", 
            "camera", "real", "life", "moments", "video", "videos"
        }
        
        topic_words = set()
        for term in search_terms:
            # Sadece harf ve rakamları al
            words = re.findall(r'\w+', term.lower())
            for w in words:
                if w not in boosters and w not in stop_words and len(w) > 2:
                    topic_words.add(w)
        
        match_count = 0
        for w in topic_words:
            if w in title:
                match_count += 1
        
        # Konu eşleşmesine devasa puan ver (Her kelime +20 puan)
        score += match_count * 20
        
        # 2. Jenerik Güçlendiriciler (Puanı düşürüldü)
        for kw in TITLE_BOOST_KEYWORDS:
            if kw in title:
                score += 1
        
        # 3. Tercih Edilen Kanallar (Puanı düşürüldü)
        for ch in PREFERRED_CHANNELS:
            if ch in channel:
                score += 1
                break
        
        # 4. Süre (3-20 dk arası ideal)
        dur = int(video.get("duration") or 0)
        if 180 <= dur <= 1200:
            score += 5
        elif dur > 1200:
            score += 2
        
        return score

    def run_yt_search(terms, count=15):
        """
        yt-dlp ile arama yap.
        PATCH:
          - ISP DNS hijack bypass (192.178.25.238)
          - timeout 60s
          - nocheckcertificate=True
        """
        yt_dlp_search_script = (
            "import sys, json, yt_dlp\n"
            "opts = {\n"
            "  'quiet': True, 'no_warnings': True, 'extract_flat': True,\n"
            "  'skip_download': True, 'playlistend': {count}, 'socket_timeout': 20,\n"
            "  'source_address': '0.0.0.0', 'retries': 2, 'fragment_retries': 2,\n"
            "  'nocheckcertificate': True,\n"
            "  'extractor_args': {'youtube': ['player_client=ios,tv']},\n"
            "}\n"
            "with yt_dlp.YoutubeDL(opts) as ydl:\n"
            "  try:\n"
            "    info = ydl.extract_info('ytsearch{count}:{terms}', download=False)\n"
            "    entries = info.get('entries', []) if info else []\n"
            "    for e in entries:\n"
            "      print(json.dumps(e))\n"
            "  except Exception as e:\n"
            "    print(f'ERROR:{e}', file=sys.stderr)\n"
        ).format(count=count, terms=terms.replace("'", "\\'"))

        # DNS override (Static IP)
        dns_patch = (
            "import socket\n"
            "_IP='192.178.25.238'\n"
            "_DOMS={'youtube.com','www.youtube.com','youtu.be','youtubei.googleapis.com'}\n"
            "_og=socket.getaddrinfo\n"
            "def _pg(h,p,*a,**k):\n"
            "  if isinstance(h,str) and any(h==d or h.endswith('.'+d) for d in _DOMS):\n"
            "    try: return _og(_IP,p,socket.AF_INET,socket.SOCK_STREAM)\n"
            "    except: pass\n"
            "  return _og(h,p,*a,**k)\n"
            "socket.getaddrinfo=_pg\n"
        )

        full_script = dns_patch + yt_dlp_search_script

        cmd = [str(VENV_PY), "-u", "-c", full_script]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                env=env,
                cwd=str(BASE_DIR),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

            if proc.stderr and proc.stderr.strip():
                print(f"[yt-dlp search] STDERR: {proc.stderr[:500]}")

            if proc.returncode != 0:
                print(f"[yt-dlp search] returncode={proc.returncode}")
                return []


            videos = []
            for line in proc.stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    v = json.loads(line)
                    dur = int(v.get("duration") or 0)
                    if dur < 120:
                        continue
                    channel_name = (
                        v.get("channel") or
                        v.get("uploader") or
                        v.get("channel_id") or ""
                    )
                    videos.append({
                        "id":        v.get("id"),
                        "title":     v.get("title"),
                        "url":       v.get("url") or f"https://www.youtube.com/watch?v={v.get('id')}",
                        "duration":  dur,
                        "thumbnail": v.get("thumbnail"),
                        "channel":   channel_name,
                    })
                except Exception:
                    pass
            return videos
        except subprocess.TimeoutExpired:
            print(f"[yt-dlp] ⏱️ Timeout (60s) — arama iptal: '{terms[:60]}'")
            return []
        except Exception as _ytdlp_exc:
            # DIAGNOSTIC: Bu sessiz kalmamalı — hangi exception olduğunu göster
            print(f"[yt-dlp] ❌ run_yt_search exception: {type(_ytdlp_exc).__name__}: {_ytdlp_exc}")
            import traceback; traceback.print_exc()
            return []

    BOOSTERS = [
        "compilation",
        "caught on camera",
        "fails funny moments",
    ]

    all_candidates = []
    seen_ids = set()

    # AI'ın verdiği ilk 2 terimi dene (hızlandırmak için)
    for term in term_list[:2]:
        results = run_yt_search(term, count=15)
        for v in results:
            if v["id"] and v["id"] not in seen_ids:
                all_candidates.append(v)
                seen_ids.add(v["id"])

    # Hâlâ yeterli temiz sonuç yoksa tek bir güçlendirici ile dene
    if len(all_candidates) < 6 and term_list:
        base_term = term_list[0]
        for booster in BOOSTERS[:1]:  # Sadece ilk booster'ı kullan
            boosted = f"{base_term} {booster}"
            results = run_yt_search(boosted, count=10)
            for v in results:
                if v["id"] and v["id"] not in seen_ids:
                    all_candidates.append(v)
                    seen_ids.add(v["id"])

    # Başlık filtresi uygula
    clean = [v for v in all_candidates if is_acceptable(v)]
    clean.sort(key=lambda v: score_video(v, term_list), reverse=True)

    # Yeterli temiz sonuç çıkmadıysa filtresiz listeyi de puana göre ekle
    if len(clean) < 3:
        seen_clean = {v["id"] for v in clean}
        unfiltered = sorted(all_candidates, key=lambda v: score_video(v, term_list), reverse=True)
        for v in unfiltered:
            if v["id"] not in seen_clean:
                clean.append(v)
                seen_clean.add(v["id"])

    final_results = clean[:5]
    if final_results:
        import httpx
        prompt = (
            "Aşağıdaki YouTube videolarından RankVibe konseptine (oyun jargonu, fail, cctv, matrix glitch tarzı chill ama vurucu gerçek hayat hataları) "
            "en uygun olan 1 tanesini seç.\n\nVideolar:\n"
        )
        for i, vid in enumerate(final_results, 1):
            dur = int(vid.get("duration") or 0)
            mins = dur // 60
            secs = dur % 60
            prompt += f"{i}. Başlık: {vid.get('title')} (Süre: {mins}:{secs:02d})\n"
        prompt += (
            "\nLütfen SADECE JSON formatında dön:\n"
            "{\n"
            "  \"recommended_index\": <1 ile 5 arası seçtiğin videonun numarası integer (1-indexed)>,\n"
            "  \"reason\": \"<Kısa, tek cümlelik nedensel açıklama (örn: Matrix glitch hissini en iyi veren fail bu.)>\"\n"
            "}\n"
        )
        
        try:
            models = list(VISION_MODELS)
            ai_success = False
            for i, model in enumerate(models, start=1):
                print(f"[ai-recommend] Model {i}/{len(models)} deneniyor: {model}")
                try:
                    resp = httpx.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=15,
                    )
                except Exception:
                    continue  # ağ/bağlantı hatası → sonraki modele geç

                if resp.status_code != 200:
                    print(f"[ai-recommend] ✗ HTTP {resp.status_code} ({model})")
                    continue  # 404/500/528 vb. → sonraki modele geç

                try:
                    rt = resp.json()["choices"][0]["message"]["content"]
                    rj = _fuzzy_parse_json(rt)
                    if rj:
                        idx = rj.get("recommended_index", 1)
                        if 1 <= int(idx) <= len(final_results):
                            final_results[int(idx) - 1]["ai_recommended"] = True
                            final_results[int(idx) - 1]["ai_reason"] = rj.get("reason", "Harika bir konsept uyumu.")
                    print(f"[ai-recommend] ✅ Başarılı: {model}")
                    ai_success = True
                    break  # başarılı → döngüden çık
                except Exception:
                    continue  # parse hatası → sonraki modele geç

            if not ai_success:
                print("[ai-recommend] ℹ Hiçbir model çalışmadı, AI önerisi eklenmedi.")
        except Exception as _ai_exc:
            print(f"[ai-recommend] ❌ Beklenmeyen hata: {type(_ai_exc).__name__}: {_ai_exc}")
            import traceback; traceback.print_exc()
            pass  # video listesi yine de döndürülür

    return jsonify(final_results)


def _extract_frame(video_path: Path, out_path: Path):
    """FFmpeg ile videonun 1. veya 0.5. saniyesinden frame alır."""
    SYSTEM_FFMPEG = shutil.which("ffmpeg")
    FFMPEG_PATH = SYSTEM_FFMPEG if SYSTEM_FFMPEG else r"C:\ffmpeg\bin\ffmpeg.exe"
    
    cmd = [
        FFMPEG_PATH, "-y", "-ss", "00:00:01", "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(out_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if out_path.exists():
            return True
    except Exception:
        pass
    
    cmd = [
        FFMPEG_PATH, "-y", "-ss", "00:00:00.5", "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(out_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if out_path.exists():
            return True
    except Exception:
        pass
    return False

def _sanitize_label(text: str) -> str:
    text = text.split("/")[0].split("\\")[0]
    text = re.sub(r"[_*+|#@^~`<>{}\[\]]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Sadece kelimelerin ilk harflerini büyük yap (Title Case), tamamı büyük olmasını engelle
    text = text.title()
    return text

def _strip_emojis(text: str) -> str:
    emoji_pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002700-\U000027BF"
        u"\U0001F900-\U0001F9FF"
        u"\U00002600-\U000026FF"
        u"\uFE00-\uFE0F"
        u"\U0001FA00-\U0001FA6F"
        u"\U0001FA70-\U0001FAFF"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()

@app.route("/api/analyze-clips", methods=["POST"])
def analyze_clips():
    """Seçilen kliplerden frame alıp yapay zekadan başlık, metinler ve x_offset döner."""
    data = request.get_json(force=True)
    selected = data.get("clips", [])
    if len(selected) != 5:
        return jsonify({"error": "Tam 5 klip seçmelisin"}), 400

    import httpx
    import base64
    
    frame_files = []
    
    for idx, clip_name in enumerate(selected):
        src = CLIP_DIR / clip_name
        frame_out = CLIP_DIR / f"temp_frame_{idx}.jpg"
        if _extract_frame(src, frame_out):
            frame_files.append((clip_name, frame_out))
        else:
            frame_files.append((clip_name, None))

    # 1. Title Call
    title_data = {
        "title_line1": "Ranking the",
        "title_line2": "Funniest Real Fails",
        "title_line3": "(wait for it 😱)"
    }
    valid_frames = [f for _, f in frame_files if f]
    
    if valid_frames:
        content = [{"type": "text", "text": (
            "You are the AI behind the RankVibe YouTube channel.\n"
            "Style: cold, technical — treats real-world events as simulation/game glitches.\n\n"
            "I am showing you frames from 5 different video clips that will be combined into ONE ranking video.\n"
            "Look at ALL images carefully and identify the OVERALL common theme across most clips.\n"
            "Return ONLY valid JSON, no markdown, no extra text:\n"
            "{\n"
            "  \"title_line1\": \"Ranking the\",\n"
            "  \"title_line2\": \"<3-4 dramatic words describing the common theme: [adjective] [sport/activity] Fails/Crashes/Glitches>\",\n"
            "  \"title_line3\": \"(wait for it 😱)\"\n"
            "}\n\n"
            "RULES: Use overarching RankVibe concept. No hallucinations. Title case. No emojis in line2."
        )}]
        for fp in valid_frames:
            try:
                with open(fp, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })
            except:
                pass
            
        for model in VISION_ONLY_MODELS:
            try:
                resp = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": content}]},
                    timeout=30  # PATCH: 60s → 30s
                )
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"]
                    result = _fuzzy_parse_json(raw)
                    if result and "title_line2" in result:
                        result["title_line2"] = _sanitize_label(_strip_emojis(result["title_line2"]))
                        title_data.update(result)
                        break
            except Exception as e:
                print(f"[analyze_clips] Title AI error with model {model}: {e}")
                continue

    # 2. Clips Analysis
    results = []
    for rank_idx, (clip_name, fp) in enumerate(frame_files):
        desc = "Pending Analysis"
        x_offset = 0
        
        if fp:
            prompt = (
                "You are the creative AI behind the RankVibe YouTube channel.\n"
                "RankVibe treats real-world events as glitches in a simulation — cold, technical, darkly funny.\n"
                "Look at this image carefully.\n"
                "Analyze the image and tell me the X-Axis offset of the MAIN EVENT/SUBJECT.\n"
                "If the main subject is perfectly in the center, x_offset is 0.\n"
                "If it's on the left, x_offset is negative (e.g., -100 to -300).\n"
                "If it's on the right, x_offset is positive (e.g., 100 to 300).\n\n"
                "Return ONLY valid JSON, no markdown:\n"
                "{\n"
                "  \"description\": \"<text>\",\n"
                "  \"x_offset\": 0\n"
                "}\n\n"
                "=== CRITICAL RULES FOR DESCRIPTION (on-screen overlay text) ===\n"
                "1. LANGUAGE: STRICTLY IN ENGLISH ONLY.\n"
                "2. LENGTH: MAXIMUM 3 to 4 words. DO NOT EXCEED 4 WORDS under any circumstances.\n"
                "3. CAPITALIZATION: Use Title Case ONLY (Capitalize The First Letter Of Each Word). NEVER use ALL CAPS.\n"
                "4. STYLE: DO NOT use plain literal descriptions like 'Dog Running' or 'Person Falling'.\n"
                "   Instead, adopt the RankVibe voice — treat the event as a PHYSICS ERROR, GAME GLITCH, or SIMULATION BUG.\n"
                "   Prioritize words from this vocabulary: Glitch, Error, Physics, Fail, Logic, Matrix, Bug, Gravity, Exploit, Anomaly, Defect.\n"
                "5. CREATIVE EXAMPLES (use this style):\n"
                "   BAD  → 'DOG RUNNING' / 'Person Falls Down' / 'CAR CRASH'\n"
                "   GOOD → 'Gravity.exe Has Stopped' / 'Physics Error Detected' / 'Matrix Glitch Incoming'\n"
                "6. STRICT VISUAL TRUTH: ONLY describe events ACTUALLY visible in the frame."
            )
            
            try:
                with open(fp, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                
                for model in VISION_ONLY_MODELS:
                    try:
                        resp = httpx.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                            json={"model": model, "messages": [{"role": "user", "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                            ]}]},
                            timeout=20  # PATCH: 40s → 20s
                        )
                        if resp.status_code == 200:
                            raw = resp.json()["choices"][0]["message"]["content"]
                            result = _fuzzy_parse_json(raw)
                            if result and "description" in result:
                                desc = _sanitize_label(result["description"])
                                x_offset_val = result.get("x_offset", 0)
                                try:
                                    x_offset = int(x_offset_val)
                                except:
                                    pass
                                break
                    except Exception as e:
                        print(f"[analyze_clips] Clip AI error with model {model}: {e}")
                        continue
            except Exception as _frame_exc:
                print(f"[analyze_clips] ❌ Frame/vision exception: {type(_frame_exc).__name__}: {_frame_exc}")
                import traceback; traceback.print_exc()
            except:
                pass
                
        results.append({
            "filename": clip_name,
            "description": desc,
            "x_offset": x_offset
        })

    return jsonify({
        "title_data": title_data,
        "clips": results
    })


@app.route("/api/cut-scenes", methods=["POST"])
def cut_scenes():
    """YouTube URL al → main_web.py çalıştır, SSE stream döndür."""
    data = request.get_json(force=True)
    url  = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL gerekli"}), 400

    job_id = f"cut_{int(time.time())}"
    _log_queues[job_id] = queue.Queue()

    cmd = [
        str(VENV_PY), "-u", str(BASE_DIR / "main_web.py"), url
    ]
    threading.Thread(target=_stream_process, args=(cmd, job_id), daemon=True).start()

    return Response(
        _sse_generator(job_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/cancel-job/<job_id>", methods=["POST"])
def cancel_job(job_id):
    """
    PATCH: Çalışan bir işi (cut-scenes / create-video) zorla durdur.
    Frontend abort controller ile çağırır.
    """
    proc = _processes.get(job_id)
    killed = False
    if proc and proc.poll() is None:
        try:
            proc.kill()
            killed = True
        except Exception as e:
            return jsonify({"error": f"Kill başarısız: {e}"}), 500

    _running.pop(job_id, None)
    _processes.pop(job_id, None)
    # Kuyruğu temizle
    q = _log_queues.pop(job_id, None)
    if q:
        try:
            while not q.empty():
                q.get_nowait()
        except Exception:
            pass

    if killed:
        return jsonify({"success": True, "message": "İş durduruldu."})
    return jsonify({"success": False, "message": "Aktif iş bulunamadı (zaten tamamlanmış olabilir)."}), 404


@app.route("/api/preview-frame", methods=["POST"])
def preview_frame():
    """Belirli bir klip için anlık önizleme (base64) oluşturur."""
    import taslak
    try:
        data = request.get_json(force=True)
        filename = data.get("filename")
        clip_index = data.get("clip_index")
        title_data = data.get("title_data", {})
        clips_data = data.get("clips_data", [])

        if not filename or clip_index is None:
            return jsonify({"error": "Eksik parametreler"}), 400

        # Thumbnail yolunu bul (Örn: 1.mp4 -> 1.jpg)
        thumb_name = Path(filename).stem + ".jpg"
        thumb_path = THUMB_DIR / thumb_name

        if not thumb_path.exists():
            return jsonify({"error": "Thumbnail bulunamadı."}), 404

        # İlgili klip verisini al
        if clip_index < len(clips_data):
            x_offset = clips_data[clip_index].get("x_offset", 0)
        else:
            x_offset = 0

        # O ana kadarki açıklamaları oluştur (Örn: clip_index = 2 ise 5, 4, 3 sıralarını içerir)
        descriptions_so_far = []
        for idx in range(clip_index + 1):
            if idx < len(clips_data):
                rank_num = 5 - idx
                desc = clips_data[idx].get("description", "Pending Analysis")
                descriptions_so_far.append((rank_num, desc))

        base64_img = taslak.generate_preview_frame(
            str(thumb_path),
            descriptions_so_far,
            title_data,
            x_offset
        )

        return jsonify({"image": base64_img})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/create-video", methods=["POST"])
def create_video():
    """Seçilen klipleri kopyala ve render_data.json kaydedip taslak.py çalıştır, SSE stream."""
    data      = request.get_json(force=True)
    selected  = data.get("clips", [])
    title_data = data.get("title_data", {})
    clips_data = data.get("clips_data", [])
    
    if len(selected) != 5:
        return jsonify({"error": "Tam 5 klip seçmelisin"}), 400

    FINAL_DIR.mkdir(exist_ok=True)
    for old in FINAL_DIR.glob("*.mp4"):
        old.unlink(missing_ok=True)
        
    for old in FINAL_DIR.glob("render_data.json"):
        old.unlink(missing_ok=True)

    for idx, clip_name in enumerate(selected):
        rank_num = 5 - idx
        src = CLIP_DIR / clip_name
        dst = FINAL_DIR / f"{rank_num}.mp4"
        if src.exists():
            shutil.copy2(str(src), str(dst))

    # Render verilerini kaydet
    render_data = {
        "title_data": title_data,
        "clips_data": clips_data
    }
    with open(FINAL_DIR / "render_data.json", "w", encoding="utf-8") as f:
        json.dump(render_data, f, indent=2, ensure_ascii=False)

    job_id = f"vid_{int(time.time())}"
    _log_queues[job_id] = queue.Queue()

    cmd = [str(VENV_PY), "-u", str(BASE_DIR / "taslak.py")]
    threading.Thread(target=_stream_process, args=(cmd, job_id), daemon=True).start()

    return Response(
        _sse_generator(job_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/clear-clips", methods=["POST"])
def clear_clips():
    """Tüm klipleri (hariç tutulanlar dışında) ve küçük resimleri temizle."""
    try:
        data = request.get_json(silent=True) or {}
        exclude_list = data.get("exclude", [])
        
        # Backend tarafında güvenli favori silinmeme kuralı
        favs = _load_favorites()
        if favs is None:
            return jsonify({"error": "favorites.json dosyası okunamıyor/bozuk. Dosyalarınızı korumak için işlem iptal edildi."}), 500
        
        exclude_set = set(exclude_list + favs)
        
        count = 0
        for p in CLIP_DIR.glob("*.mp4"):
            if p.name in exclude_set:
                continue
            p.unlink(missing_ok=True)
            count += 1
            
        for p in THUMB_DIR.glob("*.jpg"):
            original_mp4_name = p.name.replace(".jpg", ".mp4")
            if original_mp4_name in exclude_set:
                continue
            p.unlink(missing_ok=True)
            
        return jsonify({"success": True, "deleted": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/delete-clip", methods=["POST"])
def delete_clip():
    """Belirli bir klibi ve küçük resmini sil."""
    data = request.get_json(force=True)
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Eksik parametre"}), 400
        
    try:
        src = CLIP_DIR / filename
        if src.exists():
            src.unlink(missing_ok=True)
            
        thumb_name = filename.replace(".mp4", ".jpg")
        thumb_src = THUMB_DIR / thumb_name
        if thumb_src.exists():
            thumb_src.unlink(missing_ok=True)
            
        # Manuel silindiği için favorilerden de çıkaralım
        favs = _load_favorites()
        if favs is not None and filename in favs:
            favs.remove(filename)
            _save_favorites(favs)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trim-clip", methods=["POST"])
def trim_clip():
    """Mevcut bir klibi verilen start/end saniyelerine göre kırp."""
    data = request.get_json(force=True)
    filename = data.get("filename")
    start = data.get("start")
    end = data.get("end")
    if not filename or start is None or end is None:
        return jsonify({"error": "Eksik parametreler"}), 400
        
    try:
        start_sec = float(start)
        end_sec = float(end)
    except ValueError:
        return jsonify({"error": "Geçersiz saniye degeri"}), 400

    duration = end_sec - start_sec
    if duration <= 0:
        return jsonify({"error": "Bitiş süresi başlangıçtan büyük olmalıdır."}), 400

    src = CLIP_DIR / filename
    if not src.exists():
        return jsonify({"error": "Klip bulunamadı"}), 404

    tmp = CLIP_DIR / f"temp_{filename}"
    
    SYSTEM_FFMPEG = shutil.which("ffmpeg")
    FFMPEG_PATH = SYSTEM_FFMPEG if SYSTEM_FFMPEG else r"C:\ffmpeg\bin\ffmpeg.exe"

    cmd = [
        FFMPEG_PATH, "-y",
        "-ss", str(start_sec),
        "-i", str(src),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(tmp)
    ]
    
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError:
        return jsonify({"error": "Kesim işlemi (FFmpeg) başarısız oldu."}), 500
    except Exception as e:
        return jsonify({"error": f"FFmpeg sistemde bulunamadı veya bilinmeyen hata: {e}"}), 500

    src.unlink(missing_ok=True)
    tmp.rename(src)
    
    thumb_path = THUMB_DIR / filename.replace(".mp4", ".jpg")
    thumb_cmd = [
        FFMPEG_PATH, "-y", "-i", str(src),
        "-ss", str(duration * 0.4), "-vframes", "1", "-q:v", "2", str(thumb_path)
    ]
    try:
        subprocess.run(thumb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    
    return jsonify({"success": True})


@app.route("/api/output-videos")
def output_videos():
    """final_videolar/ klasöründeki ranking_*.mp4 dosyalarını listele."""
    videos = []
    if FINAL_DIR.exists():
        for f in sorted(FINAL_DIR.iterdir()):
            if f.name.startswith("ranking_") and f.suffix.lower() == ".mp4":
                videos.append({
                    "filename": f.name,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                })
    return jsonify(videos)


# ── Statik dosya servisleri ────────────────────────────────

@app.route("/clips/<path:filename>")
def serve_clip(filename):
    return send_from_directory(str(CLIP_DIR), filename)


@app.route("/thumbnails/<path:filename>")
def serve_thumb(filename):
    return send_from_directory(str(THUMB_DIR), filename)


@app.route("/output/<path:filename>")
def serve_output(filename):
    return send_from_directory(str(FINAL_DIR), filename)


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(str(BASE_DIR), 'icon.ico', mimetype='image/vnd.microsoft.icon')


# ── Main ───────────────────────────────────────────────────

if __name__ == "__main__":
    CLIP_DIR.mkdir(exist_ok=True)
    THUMB_DIR.mkdir(exist_ok=True)
    FINAL_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

    if not FFMPEG_AVAILABLE:
        print("\n" + "="*50)
        print("❌ UYARI: FFmpeg bulunamadı! Video işleme özellikleri çalışmayacaktır.")
        print("   Lütfen FFmpeg'i kurun ve PATH'e ekleyin.")
        print("="*50 + "\n")

    print("🚀 RankVibe Automation → http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)