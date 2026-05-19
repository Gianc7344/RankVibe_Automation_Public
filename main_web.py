import os
import sys
import socket
import struct
import random
import subprocess
import warnings
import shutil
import threading
import concurrent.futures
from collections import defaultdict

# Force UTF-8 output to prevent UnicodeEncodeError on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# ==========================
# 🌐 DNS HIJACKING BYPASS
# ISP 53 portunu araya girip 195.175.254.2 sahte IP'sini donduruyor.
# Bu yuzden UDP sorgusu yapmak yerine dogrudan calisan Google IP'sini (192.178.25.238) kullaniyoruz.
# ==========================
_STATIC_YOUTUBE_IP = "192.178.25.238"
_DNS_DOMAINS = {
    "youtube.com", "www.youtube.com", "youtu.be",
    "youtubei.googleapis.com"
}

_orig_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, *args, **kwargs):
    if isinstance(host, str) and any(
        host == d or host.endswith("." + d) for d in _DNS_DOMAINS
    ):
        try:
            return _orig_getaddrinfo(_STATIC_YOUTUBE_IP, port, socket.AF_INET, socket.SOCK_STREAM)
        except Exception:
            pass
    return _orig_getaddrinfo(host, port, *args, **kwargs)

socket.getaddrinfo = _patched_getaddrinfo
print("[DNS OVERRIDE] Aktif: YouTube ISP engeli (DNS Hijacking) asildi. IP: 192.178.25.238")

# Gereksiz uyarıları gizle
warnings.filterwarnings("ignore")


# Kütüphane kontrolü
try:
    from yt_dlp import YoutubeDL
    from scenedetect import SceneManager, ContentDetector, open_video
    from tqdm import tqdm
except ImportError as e:
    print(f"HATA: Gerekli kütüphaneler eksik. Lütfen şunu çalıştır:\npip install yt-dlp scenedetect tqdm opencv-python-headless")
    exit()

# ==========================
# ⚙️ AYARLAR (RANKVIBE OPTİMİZASYONU)
# ==========================
SYSTEM_FFMPEG = shutil.which("ffmpeg")
FFMPEG_PATH = SYSTEM_FFMPEG if SYSTEM_FFMPEG else r"C:\ffmpeg\bin\ffmpeg.exe"

DOWNLOAD_DIR = "downloads"
CLIP_DIR = "clips"
THUMBNAIL_DIR = "thumbnails"

THRESHOLD = 27.0

MIN_SCENE_LENGTH = 1.5
MAX_SCENE_LENGTH = 59.0
MAX_VIDEO_DURATION = 1800   # 30 dakika

# Watchdog süreleri
SCENEDETECT_TIMEOUT = 360   # 6 dakika — sahne analizi
ENCODE_TIMEOUT      = 120   # 2 dakika — tek klip encode
THUMBNAIL_TIMEOUT   = 30    # 30 saniye — thumbnail
DOWNLOAD_TIMEOUT    = 600   # 10 dakika — indirme

GENERATE_THUMBNAILS = True  
ADD_TEXT_OVERLAY = False    
USE_HYBRID_ENCODING = False 

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CLIP_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# ==========================
# 🎯 CAPTION HAVUZU
# ==========================
CAPTIONS = {
    "fail": ["OH NO", "GAME OVER", "THAT HURT", "RIP", "YIKES", "OOF", "WASTED", "FAIL"],
    "shock": ["OMG", "WHAT?!", "NO WAY", "INSANE", "UNREAL", "CRAZY", "HACKER?", "HOW?"],
    "funny": ["LOL", "BRUH", "SERIOUSLY?", "WHY", "LMAO", "DEAD", "NOPE", "BYE"],
    "unexpected": ["WAIT FOR IT", "WATCH THIS", "BOOM", "SURPRISE", "LOOK", "HOLY..."]
}

MAX_REPEAT_RATIO = 0.15
caption_usage = defaultdict(int)
total_captions = 0
last_caption = None 

# ==========================
# 🛠️ YARDIMCI FONKSİYONLAR
# ==========================

def check_ffmpeg_installed():
    if not os.path.exists(FFMPEG_PATH) and not shutil.which("ffmpeg"):
        print("\n❌ HATA: FFmpeg bulunamadı!")
        print("Lütfen FFmpeg yükleyin veya FFMPEG_PATH değişkenini script içinde düzeltin.")
        print("İndirme linki: https://ffmpeg.org/download.html")
        exit()

def cleanup_old_clips(auto_clean=False):
    """Eski klipleri temizle. Web/otomasyon modunda auto_clean=True ile çağır."""
    files = [f for f in os.listdir(CLIP_DIR) if f.endswith('.mp4')]
    
    if files:
        print(f"\n⚠️  Klasörde {len(files)} eski klip var.")
        
        if auto_clean:
            print("🤖 Web modu: Eski klipler otomatik siliniyor (Force Clean)...")
            do_clean = True
        else:
            try:
                response = input("Eski klipleri silip temiz kurulum yapılsın mı? (e/h): ").strip().lower()
                do_clean = (response == 'e')
            except EOFError:
                print("⚠️  Non-interactive mod algılandı, otomatik temizlik yapılıyor...")
                do_clean = True
        
        if do_clean:
            for f in os.listdir(CLIP_DIR):
                try: os.remove(os.path.join(CLIP_DIR, f))
                except: pass
            for f in os.listdir(THUMBNAIL_DIR):
                try: os.remove(os.path.join(THUMBNAIL_DIR, f))
                except: pass
            print("✅ Temizlik yapıldı.")

def download_video(url):
    """
    yt-dlp ile video indir.
    PATCH: socket_timeout, retries, concurrent fragments ve hard thread timeout eklendi.
    """
    print("[DOWNLOAD START] URL:", url)
    print("[DOWNLOAD START] DOWNLOAD_DIR:", os.path.abspath(DOWNLOAD_DIR))
    print("[DOWNLOAD START] FFMPEG_PATH:", FFMPEG_PATH)
    print("[DOWNLOAD START] ffmpeg exists:", os.path.exists(FFMPEG_PATH))
    output_path = os.path.join(DOWNLOAD_DIR, "video.mp4")
    
    if os.path.exists(output_path):
        try: os.remove(output_path)
        except: pass

    video_title = "Unknown_Video"

    def _progress_hook(d):
        status = d.get('status', '')
        if status == 'downloading':
            pct = d.get('_percent_str', '?%').strip()
            speed = d.get('_speed_str', '?').strip()
            print(f"[DOWNLOAD PROGRESS] {pct} @ {speed}")
        elif status == 'finished':
            print(f"[DOWNLOAD FINISHED] Dosya: {d.get('filename', '?')}")
        elif status == 'error':
            print(f"[DOWNLOAD ERROR] {d}")

    ydl_opts = {
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
        "outtmpl": output_path,
        "ffmpeg_location": os.path.dirname(FFMPEG_PATH),
        "quiet": False,         # DEBUG: output gorsun
        "no_warnings": False,   # DEBUG: uyarilari goster
        "verbose": False,       # cok fazla output olmasin
        "extract_flat": False,
        "nocheckcertificate": True,   # SSL hatasını bypass et (sabit IP kullandığımız için)
        "extractor_args": {
            "youtube": ["player_client=ios,tv", "po_token=web+MkV2_wXzJzZ0nQ8rW_Uu3yY"]
        },
        "progress_hooks": [_progress_hook],
        # ── PATCH: ag hiz iyilestirmeleri ──────────────────────────────
        "socket_timeout": 20,           # Her TCP baglantisi icin 20s
        "retries": 3,                   # Indirme yeniden deneme sayisi
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,  # Parcali indirmeyi hizlandir
        "http_chunk_size": 10485760,         # 10 MB chunk
        # ───────────────────────────────────────────────────────────────
        "source_address": "0.0.0.0",
    }

    result = {"path": None, "title": None, "error": None}

    def _download():
        try:
            print("[DOWNLOAD THREAD] YoutubeDL basliyor...")
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                result["title"] = info.get("title", "Unknown_Video")
                print(f"[DOWNLOAD THREAD] Baslik: {result['title']}")
        except Exception as e:
            import traceback
            print(f"[DOWNLOAD THREAD ERROR] {type(e).__name__}: {e}")
            traceback.print_exc()
            result["error"] = str(e)

    # PATCH: Hard timeout — indirme DOWNLOAD_TIMEOUT saniyede bitmezse iptal
    print(f"[DOWNLOAD] Thread baslatildi. Timeout={DOWNLOAD_TIMEOUT}s")
    t = threading.Thread(target=_download, daemon=True)
    t.start()
    t.join(timeout=DOWNLOAD_TIMEOUT)

    if t.is_alive():
        print(f"[DOWNLOAD TIMEOUT] {DOWNLOAD_TIMEOUT}s'de tamamlanamadi, iptal edildi.")
        return None, None

    print(f"[DOWNLOAD] Thread bitti. error={result['error']!r}, path_exists={os.path.exists(output_path)}")

    if result["error"]:
        print(f"[DOWNLOAD ERROR] {result['error']}")
        return None, None

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
        print(f"[DOWNLOAD ERROR] Dosya hatali veya bos. exists={os.path.exists(output_path)}")
        return None, None

    import re
    safe_title = re.sub(r'[\\/*?:"<>|]', "", result["title"] or "video")
    safe_title = safe_title[:40].strip()

    return output_path, safe_title


def detect_scenes(video_path):
    """
    Sahne tespiti.
    PATCH: concurrent.futures ile SCENEDETECT_TIMEOUT saniye watchdog eklendi.
    SceneDetect bazı videolarda sonsuz döngüye girebiliyordu.
    """
    print(f"[SCENE DETECT START] video_path={video_path}, exists={os.path.exists(video_path)}")

    def _run_detection():
        video = open_video(video_path)
        duration = video.duration.get_seconds()
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=THRESHOLD))
        scene_manager.detect_scenes(video=video)
        scenes = scene_manager.get_scene_list()
        return scenes, duration

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_detection)
        try:
            scenes, duration = future.result(timeout=SCENEDETECT_TIMEOUT)
            print(f"✅ Analiz bitti: {len(scenes)} sahne tespit edildi.")
            return scenes, duration
        except concurrent.futures.TimeoutError:
            print(f"❌ Sahne analizi {SCENEDETECT_TIMEOUT}s içinde tamamlanamadı, iptal edildi.")
            future.cancel()
            return [], 0
        except Exception as e:
            print(f"❌ Sahne analizi hatası: {e}")
            return [], 0


def choose_caption(position_ratio):
    global total_captions, last_caption
    
    if position_ratio < 0.2: category = "unexpected"
    elif position_ratio < 0.8: category = random.choice(["fail", "shock", "funny"])
    else: category = random.choice(["fail", "shock"])
    
    pool = CAPTIONS[category].copy()
    random.shuffle(pool)
    
    selected = None
    for cap in pool:
        if cap != last_caption:
            selected = cap
            break
    
    if not selected: selected = random.choice(pool)
    
    last_caption = selected
    return selected


def encode_clip(video_path, start, duration, output_file):
    """
    Klip kesme islemi.
    PATCH: subprocess.Popen + proc.wait(timeout) kullanimi.
    """
    print(f"[ENCODE START] start={start:.1f}s dur={duration:.1f}s out={os.path.basename(output_file)}")
    cmd = [
        FFMPEG_PATH,
        "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        output_file
    ]

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        try:
            proc.wait(timeout=ENCODE_TIMEOUT)
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            print(f"⏱️ Klip encode timeout ({ENCODE_TIMEOUT}s): {os.path.basename(output_file)}")
            proc.kill()
            proc.wait()
            # Yarım kalan çıktıyı temizle
            try:
                if os.path.exists(output_file):
                    os.remove(output_file)
            except Exception:
                pass
            return False
    except Exception as e:
        print(f"❌ Encode hatası: {e}")
        if proc:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass
        return False


def extract_thumbnail(video_file, output_jpg, duration):
    """
    PATCH: Popen + wait(timeout=THUMBNAIL_TIMEOUT) eklendi.
    """
    proc = None
    try:
        timestamp = duration * 0.4
        proc = subprocess.Popen(
            [
                FFMPEG_PATH, "-y", "-i", video_file,
                "-ss", str(timestamp), "-vframes", "1", "-q:v", "2", output_jpg
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        try:
            proc.wait(timeout=THUMBNAIL_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    except Exception:
        if proc:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass


# ==========================
# 🚀 ANA İŞLEM
# ==========================
def process_video(url, auto_clean=False):
    try:
        print("[PROCESS_VIDEO START] url=", url, "auto_clean=", auto_clean)
        check_ffmpeg_installed()
        cleanup_old_clips(auto_clean=auto_clean)

        video_path, video_title = download_video(url)
        print(f"[PROCESS_VIDEO] download_video returned: path={video_path!r}, title={video_title!r}")
        if not video_path:
            print("[PROCESS_VIDEO] Download basarisiz, cikiliyor.")
            return

        scenes, video_duration = detect_scenes(video_path)
        print(f"[PROCESS_VIDEO] detect_scenes returned: {len(scenes)} sahne, duration={video_duration:.1f}s")

        if not scenes:
            print("[PROCESS_VIDEO] Hic sahne tespit edilemedi. Durduruluyor.")
            return

        print("[PROCESS_VIDEO] Klipler olusturuluyor...")
        count = 0
        for i, scene in enumerate(tqdm(scenes, desc="Isleniyor", unit="klip")):
            start = scene[0].get_seconds()
            end = scene[1].get_seconds()
            duration = end - start

            if duration < MIN_SCENE_LENGTH: continue
            if duration > MAX_SCENE_LENGTH: continue
            if start < 5.0 or start > (video_duration - 10.0): continue

            caption = choose_caption(start / video_duration)
            safe_name = f"{video_title}_{i+1:03d}_{caption.replace(' ', '_')}"
            output_file = os.path.join(CLIP_DIR, f"{safe_name}.mp4")

            if encode_clip(video_path, start, duration, output_file):
                count += 1
                if GENERATE_THUMBNAILS:
                    extract_thumbnail(output_file, os.path.join(THUMBNAIL_DIR, f"{safe_name}.jpg"), duration)

        print(f"[PROCESS_VIDEO DONE] Toplam {count} klip olusturuldu.")
        print(f"[PROCESS_VIDEO DONE] Klipler: {os.path.abspath(CLIP_DIR)}")
    except Exception as _proc_exc:
        import traceback
        print(f"[PROCESS_VIDEO FATAL] {type(_proc_exc).__name__}: {_proc_exc}")
        traceback.print_exc()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        target_url = sys.argv[1].strip()
        if target_url:
            process_video(target_url, auto_clean=True)
    else:
        print("🎬 RANKVIBE AUTO CLIPPER V2")
        target_url = input("YouTube Video Linkini Yapıştır: ").strip()
        if target_url:
            process_video(target_url)