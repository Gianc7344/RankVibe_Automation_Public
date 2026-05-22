"""
RankVibe E2E System Test — Tam Prodüksiyon Stres Testi (5 Klip)
================================================================
Bu script, Flask sunucusunun ÇALIŞIYOR olmasını gerektirir.
Sırasıyla şu API uç noktalarını çağırır:
  1. /api/generate-idea  → AI ile fikir üret
  2. /api/search-youtube → Video bul
  3. /api/cut-scenes     → Sahne kesimi yap (SSE stream)
  4. Klasörden son 5 klibi seç
  5. /api/create-video   → 5 klip ile tam render (SSE stream)

Kullanım:
  python e2e_system_test.py
  (Önce ayrı bir terminalde: python app.py)
"""

import os
import sys
import time
import json
import requests
from pathlib import Path

# ── Windows UTF-8 Fix ──────────────────────────────────────
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

# ── Config ─────────────────────────────────────────────────
BASE_URL = "http://localhost:5000"
TIMEOUT_API = 180       # Normal API çağrıları için (YouTube araması uzun sürebilir)
TIMEOUT_SSE = 600       # SSE stream (cut-scenes, create-video) için max bekleme
BASE_DIR = Path(__file__).resolve().parent
CLIP_DIR = BASE_DIR / "clips"


def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    prefix = {"INFO": "ℹ️", "OK": "✅", "WARN": "⚠️", "FAIL": "❌", "STEP": "🔷"}
    icon = prefix.get(level, "  ")
    print(f"[{ts}] {icon}  {msg}")


def check_server():
    """Flask sunucusunun çalışıp çalışmadığını kontrol eder."""
    try:
        r = requests.get(f"{BASE_URL}/api/clips", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def consume_sse_stream(response, step_name, timeout=TIMEOUT_SSE):
    """
    SSE (Server-Sent Events) stream'ini tüketir.
    Sunucudan gelen log satırlarını yazdırır.
    'done' event'i gelene kadar veya timeout olana kadar bekler.
    Döndürür: (success: bool, exit_code: int)
    """
    start = time.time()
    exit_code = -1

    try:
        for line in response.iter_lines(decode_unicode=True):
            if time.time() - start > timeout:
                log(f"{step_name}: Zaman aşımı ({timeout}s)!", "FAIL")
                return False, -1

            if not line:
                continue

            if line.startswith("data: "):
                payload = line[6:]
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type == "log":
                    text = data.get("text", "")
                    print(f"    [{step_name}] {text}")
                elif msg_type == "done":
                    exit_code = data.get("code", 0)
                    if exit_code == 0:
                        log(f"{step_name}: Başarıyla tamamlandı.", "OK")
                        return True, 0
                    else:
                        log(f"{step_name}: Hata ile bitti (exit code: {exit_code})", "FAIL")
                        return False, exit_code
    except Exception as e:
        log(f"{step_name}: Stream hatası: {e}", "FAIL")
        return False, -1

    # Stream kapandı ama done gelmedi
    log(f"{step_name}: Stream beklenmedik şekilde kapandı.", "WARN")
    return exit_code == 0, exit_code


# ════════════════════════════════════════════════════════════
# TEST ADIMLARI
# ════════════════════════════════════════════════════════════

def step1_generate_idea():
    """ADIM 1: AI ile video fikri üret."""
    log("ADIM 1: Fikir üretimi başlatılıyor...", "STEP")

    payload = {
        "analytics": "Son videomuz 50K izlenmeye ulaştı. İzleyici kitlesi 18-34 yaş arası erkekler. "
                      "Retention %45, CTR %8. En çok izlenen: fail compilation ve close calls.",
        "channel_rules": "IRL fail compilations only. No gaming, no AI generated content.",
        "target_audience": "Young males interested in fails/bloopers",
        "target_age": "18-34",
        "previous_ideas": []
    }

    try:
        resp = requests.post(
            f"{BASE_URL}/api/generate-idea",
            json=payload,
            timeout=TIMEOUT_API
        )
    except requests.Timeout:
        log("API zaman aşımı!", "FAIL")
        return None
    except Exception as e:
        log(f"Bağlantı hatası: {e}", "FAIL")
        return None

    if resp.status_code != 200:
        log(f"API hatası {resp.status_code}: {resp.text[:200]}", "FAIL")
        return None

    data = resp.json()
    if "error" in data:
        log(f"API hata döndürdü: {data['error']}", "FAIL")
        return None

    idea = data.get("idea", "Bilinmeyen fikir")
    terms = data.get("search_terms", [])
    log(f"Fikir: {idea[:100]}", "OK")
    log(f"Arama terimleri: {terms}", "INFO")
    return data


def step2_search_youtube(idea_data):
    """ADIM 2: YouTube'da video bul."""
    log("ADIM 2: YouTube araması başlatılıyor...", "STEP")

    search_terms = idea_data.get("search_terms", ["funny fails compilation caught on camera"])

    try:
        resp = requests.post(
            f"{BASE_URL}/api/search-youtube",
            json={"search_terms": search_terms},
            timeout=TIMEOUT_API
        )
    except requests.Timeout:
        log("YouTube arama zaman aşımı!", "FAIL")
        return None
    except Exception as e:
        log(f"Bağlantı hatası: {e}", "FAIL")
        return None

    if resp.status_code != 200:
        log(f"API hatası {resp.status_code}: {resp.text[:200]}", "FAIL")
        return None

    videos = resp.json()
    if isinstance(videos, dict) and "error" in videos:
        log(f"Arama hatası: {videos['error']}", "FAIL")
        return None

    if not videos:
        log("Hiç video bulunamadı!", "FAIL")
        return None

    log(f"{len(videos)} video bulundu:", "OK")
    for i, v in enumerate(videos, 1):
        ai_mark = " ★ AI ÖNERİSİ" if v.get("ai_recommended") else ""
        dur = v.get("duration", 0)
        mins, secs = divmod(dur, 60)
        log(f"  {i}. {v.get('title', '?')[:60]} ({mins}:{secs:02d}){ai_mark}", "INFO")

    # AI önerileni veya ilk videoyu seç
    selected = next((v for v in videos if v.get("ai_recommended")), videos[0])
    video_url = selected.get("url", "")
    log(f"Seçilen video: {selected.get('title', '?')[:60]}", "OK")
    log(f"URL: {video_url}", "INFO")
    return video_url


def step3_cut_scenes(video_url):
    """ADIM 3: Sahne kesimi (SSE stream)."""
    log("ADIM 3: Sahne kesimi başlatılıyor...", "STEP")
    log(f"Video: {video_url}", "INFO")

    try:
        resp = requests.post(
            f"{BASE_URL}/api/cut-scenes",
            json={"url": video_url},
            stream=True,
            timeout=TIMEOUT_SSE
        )
    except Exception as e:
        log(f"Cut-scenes bağlantı hatası: {e}", "FAIL")
        return False

    if resp.status_code != 200:
        log(f"Cut-scenes başlatılamadı: {resp.status_code}", "FAIL")
        return False

    success, code = consume_sse_stream(resp, "cut-scenes")
    return success


def step4_select_clips():
    """ADIM 4: Klasörden en son 5 klibi seç."""
    log("ADIM 4: Klip seçimi yapılıyor...", "STEP")

    if not CLIP_DIR.exists():
        log(f"Klip klasörü bulunamadı: {CLIP_DIR}", "FAIL")
        return None

    all_clips = sorted(
        [f for f in CLIP_DIR.glob("*.mp4")],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

    clip_names = [f.name for f in all_clips]
    log(f"Toplam {len(clip_names)} klip bulundu.", "INFO")

    if len(clip_names) < 5:
        log(f"UYARI: Sadece {len(clip_names)} klip var. 5 klip gerekli!", "WARN")
        if len(clip_names) == 0:
            log("Hiç klip yok, test devam edemez!", "FAIL")
            return None
        # Stres testi için mevcut klipleri tekrarlayarak 5'e tamamla
        log("Klipleri tekrarlayarak 5'e tamamlanıyor (stres test fallback)...", "WARN")
        while len(clip_names) < 5:
            clip_names.append(clip_names[len(clip_names) % len(all_clips)])

    selected = clip_names[:5]
    log("Seçilen 5 klip:", "OK")
    for i, name in enumerate(selected, 1):
        size = (CLIP_DIR / name).stat().st_size / (1024 * 1024) if (CLIP_DIR / name).exists() else 0
        log(f"  {i}. {name} ({size:.1f} MB)", "INFO")

    return selected


def step5_create_video(selected_clips):
    """ADIM 5: 5 klip ile tam render (SSE stream) — STRES TESTİ."""
    log("ADIM 5: Video render başlatılıyor (5 klip — TAM PRODÜKSIYON)...", "STEP")

    try:
        resp = requests.post(
            f"{BASE_URL}/api/create-video",
            json={"clips": selected_clips},
            stream=True,
            timeout=TIMEOUT_SSE
        )
    except Exception as e:
        log(f"Create-video bağlantı hatası: {e}", "FAIL")
        return False

    if resp.status_code != 200:
        log(f"Create-video başlatılamadı: {resp.status_code} - {resp.text[:200]}", "FAIL")
        return False

    success, code = consume_sse_stream(resp, "create-video", timeout=TIMEOUT_SSE)
    return success


def step6_verify():
    """ADIM 6: Final video doğrulaması."""
    log("ADIM 6: Sonuçlar doğrulanıyor...", "STEP")

    try:
        resp = requests.get(f"{BASE_URL}/api/output-videos", timeout=10)
        if resp.status_code != 200:
            log(f"Output videos API hatası: {resp.status_code}", "FAIL")
            return False

        videos = resp.json()
        if not videos:
            log("Final video dosyası bulunamadı!", "FAIL")
            return False

        for v in videos:
            log(f"  ✅ {v['filename']} ({v['size_mb']} MB)", "OK")

        log(f"Toplam {len(videos)} final video oluşturuldu.", "OK")
        return True

    except Exception as e:
        log(f"Doğrulama hatası: {e}", "FAIL")
        return False


# ════════════════════════════════════════════════════════════
# ANA AKIŞ
# ════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 60)
    print("  RANKVIBE E2E STRES TESTİ — TAM PRODÜKSIYON (5 KLİP)")
    print("═" * 60 + "\n")

    start_time = time.time()

    # 0) Sunucu kontrolü
    log("Sunucu kontrolü...", "STEP")
    if not check_server():
        log("Flask sunucusu çalışmıyor!", "FAIL")
        log("Lütfen önce ayrı bir terminalde çalıştırın:", "INFO")
        log("  cd RankVibe_Automation && venv\\Scripts\\python app.py", "INFO")
        sys.exit(1)
    log("Sunucu çalışıyor.", "OK")

    results = {}

    # 1) Fikir Üretimi
    idea_data = step1_generate_idea()
    results["generate_idea"] = idea_data is not None
    if not idea_data:
        log("Fikir üretilemedi, fallback terimlerle devam ediliyor...", "WARN")
        idea_data = {"search_terms": ["funny fails compilation caught on camera 2024"]}

    # 2) YouTube Araması
    video_url = step2_search_youtube(idea_data)
    results["search_youtube"] = video_url is not None
    if not video_url:
        log("Video bulunamadı, test durduruluyor.", "FAIL")
        _print_summary(results, start_time)
        sys.exit(1)

    # 3) Sahne Kesimi
    cut_ok = step3_cut_scenes(video_url)
    results["cut_scenes"] = cut_ok
    if not cut_ok:
        log("Sahne kesimi başarısız oldu. Mevcut kliplerle devam edeniyor...", "WARN")

    # 4) Klip Seçimi
    selected = step4_select_clips()
    results["clip_selection"] = selected is not None
    if not selected:
        log("Klip seçimi başarısız, test durduruluyor.", "FAIL")
        _print_summary(results, start_time)
        sys.exit(1)

    # 5) Video Render (STRES TESTİ)
    render_ok = step5_create_video(selected)
    results["create_video"] = render_ok

    # 6) Doğrulama
    verify_ok = step6_verify()
    results["verification"] = verify_ok

    _print_summary(results, start_time)

    if all(results.values()):
        sys.exit(0)
    else:
        sys.exit(1)


def _print_summary(results, start_time):
    """Test özet raporunu yazdırır."""
    elapsed = time.time() - start_time
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    print("\n" + "═" * 60)
    print("  TEST SONUÇ RAPORU")
    print("═" * 60)

    step_names = {
        "generate_idea":  "Fikir Üretimi (AI)",
        "search_youtube": "YouTube Araması",
        "cut_scenes":     "Sahne Kesimi",
        "clip_selection":  "Klip Seçimi (5 adet)",
        "create_video":   "Video Render (5 klip stres)",
        "verification":   "Final Doğrulama",
    }

    all_passed = True
    for key, name in step_names.items():
        if key in results:
            status = "✅ BAŞARILI" if results[key] else "❌ BAŞARISIZ"
            if not results[key]:
                all_passed = False
            print(f"  {status}  {name}")

    print(f"\n  ⏱️  Toplam süre: {mins} dk {secs} sn")

    if all_passed:
        print("\n  🏆 TÜM ADIMLAR BAŞARILI — Sistem stres testini geçti!")
    else:
        print("\n  ⚠️  Bazı adımlar başarısız oldu. Yukarıdaki logları inceleyin.")

    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
