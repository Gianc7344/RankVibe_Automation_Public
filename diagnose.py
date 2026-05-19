"""
RankVibe Diagnostic Tool
========================
Kullanım: python diagnose.py

Her bileşeni sırayla test eder ve terminale GERÇEK hataları yazar.
Tüm output'u kaydetmek için: python diagnose.py > diagnose_log.txt 2>&1
"""

import sys
import os
import shutil
import subprocess
import json
import time
import traceback
import importlib

# ── Renk yardımcıları (Windows'ta da çalışır) ─────────────
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    OK   = Fore.GREEN  + "✅ OK"    + Style.RESET_ALL
    FAIL = Fore.RED    + "❌ FAIL"  + Style.RESET_ALL
    WARN = Fore.YELLOW + "⚠️  WARN"  + Style.RESET_ALL
    INFO = Fore.CYAN   + "ℹ️  INFO"  + Style.RESET_ALL
except ImportError:
    OK = "✅ OK"; FAIL = "❌ FAIL"; WARN = "⚠️  WARN"; INFO = "ℹ️  INFO"

SEP = "=" * 65

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def ok(msg):   print(f"  {OK}   {msg}")
def fail(msg): print(f"  {FAIL} {msg}")
def warn(msg): print(f"  {WARN} {msg}")
def info(msg): print(f"  {INFO} {msg}")

# ═══════════════════════════════════════════════════════════
# 1. PYTHON VERSİYON
# ═══════════════════════════════════════════════════════════
section("1. Python Versiyonu")
v = sys.version_info
info(f"Python {v.major}.{v.minor}.{v.micro} — {sys.executable}")
if v.major < 3 or (v.major == 3 and v.minor < 9):
    fail("Python 3.9+ gerekli!")
else:
    ok(f"Python versiyonu uygun.")

# ═══════════════════════════════════════════════════════════
# 2. GEREKLİ KÜTÜPHANELERİ KONTROL ET
# ═══════════════════════════════════════════════════════════
section("2. Python Paketleri")
REQUIRED = {
    "flask":       "Flask",
    "yt_dlp":      "yt-dlp",
    "scenedetect": "scenedetect",
    "tqdm":        "tqdm",
    "cv2":         "opencv-python-headless",
    "httpx":       "httpx",
}
all_pkgs_ok = True
for mod, pkg in REQUIRED.items():
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "?")
        ok(f"{pkg} — v{ver}")
    except ImportError as e:
        fail(f"{pkg} EKSİK → pip install {pkg}")
        all_pkgs_ok = False

if not all_pkgs_ok:
    fail("Eksik paketler var! Önce bunları kur, sonra devam et.")

# yt-dlp versiyon uyarısı
try:
    import yt_dlp
    ver_str = getattr(yt_dlp.version, "__version__", "?")
    info(f"yt-dlp versiyon: {ver_str}")
    # 2024.04 ve öncesi YouTube'da sorun çıkarabilir
    try:
        year = int(str(ver_str).split(".")[0])
        if year < 2024:
            warn("yt-dlp ESKIYDI! Güncellemek için: pip install -U yt-dlp")
        else:
            ok("yt-dlp versiyonu güncel görünüyor.")
    except Exception:
        warn(f"yt-dlp versiyonu parse edilemedi: {ver_str}")
except Exception:
    pass

# ═══════════════════════════════════════════════════════════
# 3. FFMPEG
# ═══════════════════════════════════════════════════════════
section("3. FFmpeg")
ffmpeg_path = shutil.which("ffmpeg")
ffprobe_path = shutil.which("ffprobe")

if ffmpeg_path:
    ok(f"ffmpeg bulundu: {ffmpeg_path}")
else:
    # Windows sabit yol dene
    fallback = r"C:\ffmpeg\bin\ffmpeg.exe"
    if os.path.exists(fallback):
        ffmpeg_path = fallback
        warn(f"ffmpeg PATH'te yok ama sabit yolda bulundu: {fallback}")
        warn("PATH'e eklemek performansı artırır.")
    else:
        fail("ffmpeg bulunamadı! PATH'e ekle veya C:\\ffmpeg\\bin\\ffmpeg.exe'ye koy.")
        fail("İndirme: https://ffmpeg.org/download.html")
        ffmpeg_path = None

if ffprobe_path:
    ok(f"ffprobe bulundu: {ffprobe_path}")
else:
    warn("ffprobe bulunamadı (bazı özellikler bozuk olabilir)")

if ffmpeg_path:
    # Versiyon çıktısı al
    try:
        res = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True, text=True, timeout=10
        )
        first_line = res.stdout.splitlines()[0] if res.stdout else res.stderr.splitlines()[0]
        ok(f"ffmpeg version: {first_line}")
    except subprocess.TimeoutExpired:
        fail("ffmpeg -version komutu timeout aldı!")
    except Exception as e:
        fail(f"ffmpeg çalıştırılamadı: {e}")

    # Gerçek encode testi: 3 saniyelik sessiz video oluştur
    test_out = "_diag_test.mp4"
    try:
        res = subprocess.run(
            [ffmpeg_path, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25",
             "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", test_out],
            capture_output=True, text=True, timeout=30
        )
        if os.path.exists(test_out) and os.path.getsize(test_out) > 100:
            ok("FFmpeg encode testi başarılı (libx264 çalışıyor)")
            os.remove(test_out)
        else:
            fail("FFmpeg encode çıktısı boş veya hatalı!")
            if res.stderr:
                print("  --- STDERR ---")
                for ln in res.stderr.splitlines()[-10:]:
                    print(f"  {ln}")
    except subprocess.TimeoutExpired:
        fail("FFmpeg encode testi timeout aldı!")
    except Exception as e:
        fail(f"FFmpeg encode testi: {e}")
        traceback.print_exc()

# ═══════════════════════════════════════════════════════════
# 4. YT-DLP — YouTube arama testi
# ═══════════════════════════════════════════════════════════
section("4. yt-dlp YouTube Arama Testi")
info("5-10 saniye sürebilir, bekliyoruz...")
yt_cmd = [
    "yt-dlp",
    "--force-ipv4",
    "--flat-playlist",
    "--dump-json",
    "--no-playlist",
    "--ignore-errors",
    "--no-warnings",
    "--socket-timeout", "15",
    "--extractor-retries", "1",
    "--playlist-end", "3",
    "ytsearch3:funny fails compilation"
]
try:
    t0 = time.time()
    res = subprocess.run(
        yt_cmd,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )
    elapsed = time.time() - t0
    info(f"yt-dlp çalıştı — {elapsed:.1f}s, returncode={res.returncode}")

    if res.returncode != 0:
        fail(f"yt-dlp returncode={res.returncode}")
        if res.stderr:
            print("  --- STDERR (son 20 satır) ---")
            for ln in res.stderr.splitlines()[-20:]:
                print(f"  {ln}")
    else:
        lines = [l for l in res.stdout.splitlines() if l.strip()]
        parsed = 0
        for line in lines:
            try:
                v = json.loads(line)
                if v.get("id"):
                    parsed += 1
                    ok(f"Sonuç #{parsed}: {v.get('title','?')[:60]}")
            except Exception:
                pass
        if parsed == 0:
            fail("yt-dlp çıktı aldı ama JSON parse edilemedi!")
            print("  --- RAW STDOUT (ilk 500 karakter) ---")
            print(res.stdout[:500])
            if res.stderr:
                print("  --- STDERR ---")
                print(res.stderr[:500])
        else:
            ok(f"Toplam {parsed} video sonucu parse edildi.")

except subprocess.TimeoutExpired:
    fail("yt-dlp arama 60 saniyede bitmedi! İnternet bağlantısı veya YouTube bloğu olabilir.")
except FileNotFoundError:
    fail("yt-dlp komutu bulunamadı! PATH'te yok mu?")
    fail("Çözüm: pip install yt-dlp  VEYA  venv'in aktif olduğundan emin ol")
except Exception as e:
    fail(f"yt-dlp arama hatası: {type(e).__name__}: {e}")
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════
# 5. YT-DLP — Video indirme testi (küçük bir video)
# ═══════════════════════════════════════════════════════════
section("5. yt-dlp Video İndirme Testi")
TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo" — 18 saniye
info(f"Test URL: {TEST_URL} (18 saniyelik ilk YouTube videosu)")
info("30 saniye sürebilir...")

os.makedirs("downloads", exist_ok=True)
test_dl_path = "downloads/_diag_download_test.mp4"
if os.path.exists(test_dl_path):
    os.remove(test_dl_path)

try:
    from yt_dlp import YoutubeDL
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": test_dl_path,
        "quiet": False,        # DIAGNOSTIC: quiet=False — tam çıktı göster
        "no_warnings": False,
        "socket_timeout": 20,
        "retries": 2,
    }
    t0 = time.time()
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([TEST_URL])
    elapsed = time.time() - t0

    if os.path.exists(test_dl_path) and os.path.getsize(test_dl_path) > 1000:
        size_mb = os.path.getsize(test_dl_path) / (1024 * 1024)
        ok(f"İndirme başarılı — {size_mb:.2f} MB, {elapsed:.1f}s")
        os.remove(test_dl_path)
    else:
        fail("İndirme tamamlandı ama dosya boş/yok!")

except Exception as e:
    fail(f"İndirme hatası: {type(e).__name__}: {e}")
    print()
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════
# 6. SCENEDETECT testi
# ═══════════════════════════════════════════════════════════
section("6. SceneDetect Testi")

# Önce test videosu oluştur (ffmpeg ile)
test_video = "_diag_scene_test.mp4"
if ffmpeg_path:
    try:
        # 10 saniyelik renkli test videosu
        res = subprocess.run(
            [ffmpeg_path, "-y",
             "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=25",
             "-c:v", "libx264", "-preset", "ultrafast", test_video],
            capture_output=True, text=True, timeout=30
        )
        if os.path.exists(test_video) and os.path.getsize(test_video) > 100:
            ok("Test videosu oluşturuldu.")

            # SceneDetect çalıştır
            try:
                import concurrent.futures
                from scenedetect import SceneManager, ContentDetector, open_video

                def _run():
                    video = open_video(test_video)
                    sm = SceneManager()
                    sm.add_detector(ContentDetector(threshold=27.0))
                    sm.detect_scenes(video=video)
                    return sm.get_scene_list()

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(_run)
                    scenes = fut.result(timeout=60)
                ok(f"SceneDetect çalıştı — {len(scenes)} sahne tespit edildi.")
            except concurrent.futures.TimeoutError:
                fail("SceneDetect 60s'de bitmedi — kilitlenme var!")
            except Exception as e:
                fail(f"SceneDetect hatası: {type(e).__name__}: {e}")
                traceback.print_exc()
        else:
            warn("Test videosu oluşturulamadı, SceneDetect testi atlandı.")
    except Exception as e:
        warn(f"Test videosu hatası: {e}")
    finally:
        if os.path.exists(test_video):
            os.remove(test_video)
else:
    warn("FFmpeg yok, SceneDetect testi atlandı.")

# ═══════════════════════════════════════════════════════════
# 7. OPENROUTER API bağlantısı
# ═══════════════════════════════════════════════════════════
section("7. OpenRouter API Bağlantısı")
try:
    import httpx

    # app.py'den API key'i al
    API_KEY = None
    try:
        with open("app.py", "r", encoding="utf-8") as f:
            for line in f:
                if 'API_KEY' in line and '=' in line and 'sk-or' in line:
                    API_KEY = line.split('"')[1]
                    break
    except Exception:
        pass

    if not API_KEY:
        warn("API key app.py'den okunamadı, test atlandı.")
    else:
        info(f"API key bulundu: {API_KEY[:15]}...")
        t0 = time.time()
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "messages": [{"role": "user", "content": "Say PONG and nothing else."}],
            },
            timeout=20,
        )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            ok(f"OpenRouter yanıt: '{content.strip()[:40]}' — {elapsed:.1f}s")
        elif resp.status_code == 401:
            fail(f"API key geçersiz veya süresi dolmuş! HTTP 401")
        elif resp.status_code == 429:
            warn(f"Rate limit (HTTP 429) — API çalışıyor ama kota aşıldı.")
        else:
            fail(f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}")

except Exception as e:
    fail(f"OpenRouter bağlantı hatası: {type(e).__name__}: {e}")
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════
# 8. PORT 5000 ÇAKIŞMA KONTROLÜ
# ═══════════════════════════════════════════════════════════
section("8. Port 5000 Durumu")
try:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    result = s.connect_ex(("127.0.0.1", 5000))
    s.close()
    if result == 0:
        warn("Port 5000 KULLANILIYOR — app.py zaten çalışıyor veya başka bir uygulama var.")
        warn("Eğer iki kez başlattıysan biri kapat.")
    else:
        ok("Port 5000 boş — app.py başlatılabilir.")
except Exception as e:
    warn(f"Port kontrolü yapılamadı: {e}")

# ═══════════════════════════════════════════════════════════
# ÖZET
# ═══════════════════════════════════════════════════════════
section("SONUÇ — Terminale Bakman Gereken Satırlar")
print("""
  1. Yukarıda ❌ olan her satır root cause adayı.
  2. ❌ yoksa ama app hâlâ donuyorsa:
       → python app.py çalıştır
       → tarayıcıdan işlemi tetikle
       → terminalde [FLASK GLOBAL ERROR] veya [subprocess STDERR] satırlarını ara
  3. En yaygın sorunlar ve çözümleri:
     ┌─────────────────────────────────────────────────────┐
     │ SORUN                   │ ÇÖZÜM                     │
     ├─────────────────────────┼───────────────────────────┤
     │ yt-dlp bulunamadı       │ pip install yt-dlp        │
     │ yt-dlp eski             │ pip install -U yt-dlp     │
     │ ffmpeg PATH'te yok      │ PATH'e ekle               │
     │ API key 401             │ OpenRouter'dan yeni key   │
     │ Port 5000 dolu          │ Eski instance'ı kapat     │
     │ SceneDetect kilitlenme  │ main_web.py patch'i gerek │
     └─────────────────────────┴───────────────────────────┘
""")