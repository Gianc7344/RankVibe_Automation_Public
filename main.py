import os
import subprocess
import random
import warnings
import shutil
from collections import defaultdict

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
# FFmpeg'i otomatik bulmaya çalış, bulamazsa elle girilen yolu kullan
SYSTEM_FFMPEG = shutil.which("ffmpeg")
FFMPEG_PATH = SYSTEM_FFMPEG if SYSTEM_FFMPEG else r"C:\ffmpeg\bin\ffmpeg.exe"

DOWNLOAD_DIR = "downloads"
CLIP_DIR = "clips"
THUMBNAIL_DIR = "thumbnails"

# Sahne Algılama Hassasiyeti (Düşük = Daha hassas, Yüksek = Daha az kesim)
# Oyun videoları hareketli olduğu için 30.0 idealdir.
THRESHOLD = 30.0 

MIN_SCENE_LENGTH = 3.0      # ✅ 2 saniye bazen çok kısa oluyor, 3 ideal.
MAX_SCENE_LENGTH = 59.0     # ✅ Shorts için max sınır.
MAX_VIDEO_DURATION = 1800   # ✅ 30 dakika

GENERATE_THUMBNAILS = True  
ADD_TEXT_OVERLAY = False    

# ⚠️ ÖNEMLİ DEĞİŞİKLİK: Sahne kesimlerinin milimetrik olması için
# hibrit modu kapattım. Re-encode biraz yavaş sürer ama kesimler kaymaz.
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
    """Eski klipleri temizle"""
    files = [f for f in os.listdir(CLIP_DIR) if f.endswith('.mp4')]
    
    if files:
        print(f"\n⚠️  Klasörde {len(files)} eski klip var.")
        
        if auto_clean:
            do_clean = True
        else:
            response = input("Eski klipleri silip temiz kurulum yapılsın mı? (e/h): ").strip().lower()
            do_clean = (response == 'e')
        
        if do_clean:
            for f in os.listdir(CLIP_DIR):
                try: os.remove(os.path.join(CLIP_DIR, f))
                except: pass
            for f in os.listdir(THUMBNAIL_DIR):
                try: os.remove(os.path.join(THUMBNAIL_DIR, f))
                except: pass
            print("✅ Temizlik yapıldı.")

def download_video(url):
    print("\n🎬 Video indiriliyor...")
    output_path = os.path.join(DOWNLOAD_DIR, "video.mp4")
    
    if os.path.exists(output_path):
        try: os.remove(output_path)
        except: pass

    video_title = "Unknown_Video"

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_path,
        "ffmpeg_location": os.path.dirname(FFMPEG_PATH), # ffmpeg.exe değil klasörü ister
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        # YouTube bot koruması için sahte tarayıcı izleri
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"},
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info.get('title', 'Unknown_Video')
    except Exception as e:
        print(f"\n❌ İndirme hatası: {e}")
        return None, None

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
        print("❌ İndirilen dosya hatalı veya boş.")
        return None, None
        
    import re
    # Başlığı dosya sistemi için güvenli hale getir
    safe_title = re.sub(r'[\\/*?:"<>|]', "", video_title)
    safe_title = safe_title[:40].strip()

    return output_path, safe_title

def detect_scenes(video_path):
    print("\n👀 Sahne Analizi Yapılıyor (Bu işlem işlemci gücüne göre sürer)...")
    
    video = open_video(video_path)
    duration = video.duration.get_seconds()
    
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=THRESHOLD))
    
    # Videonun tamamını işle
    scene_manager.detect_scenes(video=video)
    scenes = scene_manager.get_scene_list()
    
    print(f"✅ Analiz bitti: {len(scenes)} sahne tespit edildi.")
    return scenes, duration

def choose_caption(position_ratio):
    global total_captions, last_caption
    
    if position_ratio < 0.2: category = "unexpected"
    elif position_ratio < 0.8: category = random.choice(["fail", "shock", "funny"])
    else: category = random.choice(["fail", "shock"])
    
    pool = CAPTIONS[category].copy()
    random.shuffle(pool)
    
    # Ardışık tekrarı önle
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
    Klip kesme işlemi.
    Rankvibe için en önemli kısım: Jilet gibi kesim için re-encode yapıyoruz.
    """
    cmd = [
        FFMPEG_PATH,
        "-y",                   # Üzerine yaz
        "-ss", str(start),      # Başlangıç (Inputtan önce verilmeli ki hızlı olsun)
        "-i", video_path,       # Girdi
        "-t", str(duration),    # Süre
        # Görüntü Ayarları (Kaliteyi koru ama dosya boyutu şişmesin)
        "-c:v", "libx264",      
        "-preset", "veryfast",  # İşlem hızı (ultrafast çok bozar, veryfast iyidir)
        "-crf", "23",           # Kalite (18-28 arası, 23 standart)
        # Ses Ayarları
        "-c:a", "aac",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero", # Senkronizasyon kaymasını önle
        output_file
    ]
    
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def extract_thumbnail(video_file, output_jpg, duration):
    try:
        # Videonun %40'ıncı saniyesinden al (Genelde aksiyon oradadır)
        timestamp = duration * 0.4
        subprocess.run([
            FFMPEG_PATH, "-y", "-i", video_file, 
            "-ss", str(timestamp), "-vframes", "1", "-q:v", "2", output_jpg
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

# ==========================
# 🚀 ANA İŞLEM
# ==========================
def process_video(url, auto_clean=False):
    check_ffmpeg_installed()
    cleanup_old_clips(auto_clean=auto_clean)
    
    video_path, video_title = download_video(url)
    if not video_path: return

    scenes, video_duration = detect_scenes(video_path)
    
    print("\n✂️  Klipler Oluşturuluyor...")
    
    count = 0
    # Progress bar ile göster
    for i, scene in enumerate(tqdm(scenes, desc="İşleniyor", unit="klip")):
        start = scene[0].get_seconds()
        end = scene[1].get_seconds()
        duration = end - start
        
        # FİLTRELER (Rankvibe Kalite Kontrolü)
        if duration < MIN_SCENE_LENGTH: continue # Çok kısa
        if duration > MAX_SCENE_LENGTH: continue # Shorts sınırını geçerse atla
        # Giriş ve çıkış jeneriklerini atla (ilk 5 sn ve son 10 sn)
        if start < 5.0 or start > (video_duration - 10.0): continue

        # İsimlendirme: Başlık + Sıra Numarası + Olay Türü
        caption = choose_caption(start / video_duration)
        safe_name = f"{video_title}_{i+1:03d}_{caption.replace(' ', '_')}"
        output_file = os.path.join(CLIP_DIR, f"{safe_name}.mp4")
        
        # Kesim
        if encode_clip(video_path, start, duration, output_file):
            count += 1
            # Thumbnail
            if GENERATE_THUMBNAILS:
                extract_thumbnail(output_file, os.path.join(THUMBNAIL_DIR, f"{safe_name}.jpg"), duration)
    
    print(f"\n✨ İşlem Tamamlandı! Toplam {count} adet klip oluşturuldu.")
    print(f"📂 Klipler: {os.path.abspath(CLIP_DIR)}")

if __name__ == "__main__":
    print("🎬 RANKVIBE AUTO CLIPPER V2")
    target_url = input("YouTube Video Linkini Yapıştır: ").strip()
    if target_url:
        process_video(target_url)