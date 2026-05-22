import os
import re
import gc
import time
import base64
import io
import httpx
import json
import psutil
from moviepy import VideoFileClip, CompositeVideoClip, concatenate_videoclips, ImageClip, AudioFileClip, CompositeAudioClip
import moviepy.audio.fx as afx
import moviepy.video.fx as vfx
from PIL import Image, ImageDraw, ImageFont
import numpy as np

def clean_text(text):
    # Sadece ASCII karakterleri, sayıları ve yaygın işaretleri tutar, emojileri ve kutucukları siler
    if not isinstance(text, str):
        return text
    return re.sub(r'[^\x00-\x7F]+', '', text).strip()


# ============================================================
# AYARLAR
# ============================================================
def _load_env_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
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

MY_API_KEY  = _load_env_key()
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.abspath(os.path.join(BASE_DIR, "fonts", "Montserrat13", "Montserrat-Bold.ttf"))

# ── Font Fallback Çözümleme ────────────────────────────────
_SYSTEM_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\verdana.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\helvetica.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

def _resolve_font_path():
    """Kullanılabilir bir font yolu döndürür. Montserrat > Sistem fontları > None."""
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    for fp in _SYSTEM_FONT_CANDIDATES:
        if os.path.exists(fp):
            print(f"  ⚠️ Montserrat bulunamadı, fallback font: {fp}")
            return fp
    print("  ❌ Hiçbir TrueType font bulunamadı! Varsayılan bitmap font kullanılacak.")
    return None

ACTIVE_FONT_PATH = _resolve_font_path()

def _get_memory_mb():
    """Mevcut sürecin RAM kullanımını MB olarak döndürür."""
    try:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0
CLIP_FOLDER = os.path.join(BASE_DIR, "final_videolar")
TOTAL_CLIPS = 5
# ============================================================
# SABİTLER
# ============================================================
VIDEO_W    = 1080
VIDEO_H    = 1920
TEMP_FRAME = "temp_frame.jpg"


# ---- Renkler ----
RED    = (255,   0,   0)   # #FF0000
YELLOW = (255, 202,   0)   # #FFCA00
BLUE   = (  0, 142, 255)   # #008EFF
WHITE  = (255, 255, 255)
BLACK  = (  0,   0,   0)

# Sıralama renkleri: 1=kırmızı, 2=sarı, 3=mavi, 4-5=beyaz
RANK_COLORS = {1: RED, 2: YELLOW, 3: BLUE, 4: WHITE, 5: WHITE}
RANK_EMOJIS = {1: "✅", 2: "📉", 3: "🌊", 4: "🌪️", 5: "💥"}

# ---- Layout ----
HEADER_H  = 230    # Üstteki siyah blok yüksekliği
FOOTER_H  = 230    # Alttaki siyah blok yüksekliği

# Header içi metin Y konumları
H_LINE1_Y = 24     # "Ranking the" satırı
H_LINE2_Y = 96     # renkli konu satırı
H_LINE3_Y = 175    # "(wait for it 😱)"

# Sıralama öğeleri sabit Y konumları — ekranın ortasında
# (header 230px, footer 230px → içerik alanı: 230..1690 = 1460px, 5 öğe = her biri ~240px)
ITEM_Y = {
    1: 430,
    2: 630,
    3: 830,
    4: 1030,
    5: 1230,
}
LIST_LEFT_X = 42    # soldan girinti (biraz sola)

# Footer içi Y konumları
BRAND_OFFSET = 22
SUB_OFFSET   = 115

# Font boyutları
FS_H1   = 52
FS_H2   = 66
FS_H3   = 54
FS_RANK = 72
FS_BRD  = 50
FS_SUB  = 58




def extract_frame(video_path, out_path):
    try:
        c = VideoFileClip(video_path)
        c.save_frame(out_path, t=c.duration / 2.0)
        c.close()
        return True
    except Exception as e:
        print(f"  Frame alınamadı: {e}")
        return False


# ============================================================
# OVERLAY ÇIZIMI
# ============================================================

def load_fonts():
    """Fontları yükler. ACTIVE_FONT_PATH fallback mekanizmasını kullanır."""
    try:
        fpath = ACTIVE_FONT_PATH
        if fpath and os.path.exists(fpath):
            return {
                "h1":    ImageFont.truetype(fpath, FS_H1),
                "h2":    ImageFont.truetype(fpath, FS_H2),
                "h3":    ImageFont.truetype(fpath, FS_H3),
                "rank":  ImageFont.truetype(fpath, FS_RANK),
                "brand": ImageFont.truetype(fpath, FS_BRD),
                "sub":   ImageFont.truetype(fpath, FS_SUB),
            }
        raise FileNotFoundError("Kullanılabilir font yolu yok.")
    except Exception as e:
        print(f"  ❌ Font yükleme hatası ({e}), varsayılan bitmap font kullanılıyor.")
        d = ImageFont.load_default()
        return {k: d for k in ["h1","h2","h3","rank","brand","sub"]}


def tw(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def draw_stroke(draw, x, y, text, font, fill, sw=3):
    for dx in range(-sw, sw + 1):
        for dy in range(-sw, sw + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill=BLACK)
    draw.text((x, y), text, font=font, fill=fill)


def draw_centered(draw, y, text, font, fill, sw=3):
    x = (VIDEO_W - tw(draw, text, font)) // 2
    draw_stroke(draw, x, y, text, font, fill, sw)


def draw_words_centered(draw, y, words, colors, font, sw=3):
    """
    Kelime listesini farklı renklerde, ortalı yan yana çizer.
    colors: her kelime için renk (tuple veya None → WHITE)
    """
    sp_w   = tw(draw, " ", font)
    widths = [tw(draw, w, font) for w in words]
    total  = sum(widths) + sp_w * max(0, len(words) - 1)
    x      = (VIDEO_W - total) // 2
    for i, word in enumerate(words):
        col = colors[i] if i < len(colors) else WHITE
        if col is None:
            col = WHITE
        draw_stroke(draw, x, y, word, font, col, sw)
        x += widths[i] + sp_w



def draw_line_with_emoji(draw, y, text, font, fill, sw=2):
    """
    Metni Montserrat ile, emojileri Segoe UI Emoji ile ortalı cizer.
    """
    emoji_pattern = re.compile(
        "["
        u"\U0001F300-\U0001F9FF"
        u"\U0001FA00-\U0001FAFF"
        u"\U00002600-\U000027BF"
        u"\uFE00-\uFE0F"
        "]+",
        flags=re.UNICODE,
    )
    tokens = []
    last = 0
    for m in emoji_pattern.finditer(text):
        if m.start() > last:
            tokens.append((text[last:m.start()], False))
        tokens.append((m.group(), True))
        last = m.end()
    if last < len(text):
        tokens.append((text[last:], False))

    try:
        efont = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", font.size)
    except Exception:
        efont = None

    def tok_w(tok, is_emoji):
        f = efont if (is_emoji and efont) else font
        bb = draw.textbbox((0, 0), tok, font=f)
        return bb[2] - bb[0]

    total_w = sum(tok_w(tok, ie) for tok, ie in tokens)
    cx = (VIDEO_W - total_w) // 2

    for tok, is_emoji in tokens:
        f = efont if (is_emoji and efont) else font
        w = tok_w(tok, is_emoji)
        if is_emoji and efont:
            draw.text((cx, y), tok, font=f, embedded_color=True)
        else:
            draw_stroke(draw, cx, y, tok, f, fill, sw)
        cx += w


def color_title_words(words):
    """
    Başlık kelimelerini renklendirir:
      - İlk kelime (adjective): YELLOW
      - Son kelime (Fails/Crashes/...): BLUE
      - Ortadaki kelime(ler): WHITE
    Örn: ['Funniest', 'Bike', 'Fails'] → [YELLOW, WHITE, BLUE]
    Örn: ['Rarest', 'Fails']           → [YELLOW, BLUE]
    """
    n = len(words)
    if n == 0:
        return []
    if n == 1:
        return [YELLOW]
    colors = [WHITE] * n
    colors[0]  = YELLOW   # ilk kelime sarı
    colors[-1] = BLUE     # son kelime mavi
    return colors


def make_overlay(descriptions_so_far, title_data, duration):
    img  = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    F    = load_fonts()

    # ── HEADER siyah blok ──────────────────────────────────
    hbg = Image.new("RGBA", (VIDEO_W, HEADER_H), (0, 0, 0, 245))
    img.paste(hbg, (0, 0), hbg)

    # Satır 1: "Ranking" (RED) + " the" (WHITE) — ortalı birlikte
    line1_words  = ["Ranking", "the"]
    line1_colors = [RED, WHITE]
    draw_words_centered(draw, H_LINE1_Y, line1_words, line1_colors, F["h1"], sw=2)

    # Satır 2: renkli konu başlığı — auto-fit
    line2_text   = clean_text(title_data.get("title_line2", "Funniest Bike Fails"))
    line2_words  = line2_text.split()
    line2_colors = color_title_words(line2_words)
    h2_font = F["h2"]
    h2_fs   = FS_H2
    sp_w    = tw(draw, " ", h2_font)
    total_w = sum(tw(draw, w, h2_font) for w in line2_words) + sp_w * max(0, len(line2_words) - 1)
    while total_w > VIDEO_W - 80 and h2_fs > 40:
        h2_fs  -= 2
        if ACTIVE_FONT_PATH:
            h2_font = ImageFont.truetype(ACTIVE_FONT_PATH, h2_fs)
        else:
            break  # Bitmap font resize edilemez
        sp_w    = tw(draw, " ", h2_font)
        total_w = sum(tw(draw, w, h2_font) for w in line2_words) + sp_w * max(0, len(line2_words) - 1)
    draw_words_centered(draw, H_LINE2_Y, line2_words, line2_colors, h2_font, sw=3)

    # Satır 3: "(wait for it 😱)" — emoji destekli çizim
    line3 = title_data.get("title_line3", "(wait for it \U0001f631)")
    # line3 is drawn with `draw_line_with_emoji` which explicitly handles emojis using seguiemj.ttf.
    # We should probably still let it handle emojis, but if user explicitly asks to clean all...
    # Wait, the user said "tüm değişkenlere (başlık ve klip metinleri)". 
    # Let's clean line3 as well, or just title_line2 and desc.
    # Emojis on line3 are rendered correctly by `draw_line_with_emoji` and `seguiemj.ttf`.
    # Let's clean line3 too just to be safe according to user prompt.
    line3 = clean_text(line3)
    draw_line_with_emoji(draw, H_LINE3_Y, line3, F["h3"], WHITE, sw=2)

    # ── FOOTER siyah blok ──────────────────────────────────
    footer_y = VIDEO_H - FOOTER_H
    fbg = Image.new("RGBA", (VIDEO_W, FOOTER_H), (0, 0, 0, 245))
    img.paste(fbg, (0, footer_y), fbg)

    draw_centered(draw, footer_y + BRAND_OFFSET, "@RankVibe", F["brand"], WHITE, sw=2)

    # "Subscribe for more:D" — Subscribe=RED, for=YELLOW, more:D=BLUE
    sub_words  = ["Subscribe", "for", "more:D"]
    sub_colors = [RED, YELLOW, BLUE]
    draw_words_centered(draw, footer_y + SUB_OFFSET, sub_words, sub_colors, F["sub"], sw=3)

    # ── SIRALAMA LİSTESİ — auto-fit ────────────────────────
    MAX_RANK_W = VIDEO_W - LIST_LEFT_X - 40   # sağdan 40px boşluk
    for rank_num, desc in descriptions_so_far:
        y_pos = ITEM_Y.get(rank_num, 260 + (rank_num - 1) * 195)
        color = RANK_COLORS.get(rank_num, WHITE)
        emoji = RANK_EMOJIS.get(rank_num, "")
        main_text = clean_text(f"{rank_num}. {desc}")

        # SABİT font boyutu (Tek Satır Çizimi)
        rank_fs = 60
        if ACTIVE_FONT_PATH:
            rank_font = ImageFont.truetype(ACTIVE_FONT_PATH, rank_fs)
        else:
            rank_font = F["rank"]
        
        draw_stroke(draw, LIST_LEFT_X, y_pos, main_text, rank_font, color, sw=4)
        
        # Emojiyi metnin sağına ekle
        if emoji:
            text_w = draw.textlength(main_text, font=rank_font)
            try:
                emoji_font = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", rank_fs)
                emoji_x = LIST_LEFT_X + text_w + 12
                draw.text((emoji_x, y_pos), emoji, font=emoji_font, embedded_color=True)
            except Exception:
                pass

    return np.array(img)


# ============================================================
# ÖNİZLEME (PREVIEW) İŞLEMLERİ (PIL tabanlı)
# ============================================================

def pil_resize_to_916(img, x_offset=0):
    ow, oh = img.size
    if ow / oh > VIDEO_W / VIDEO_H:
        nh = VIDEO_H
        nw = int(ow * VIDEO_H / oh)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        
        try: x_offset = int(x_offset)
        except Exception: x_offset = 0

        x_c = nw // 2 + x_offset
        if x_c - VIDEO_W // 2 < 0:
            x_c = VIDEO_W // 2
        elif x_c + VIDEO_W // 2 > nw:
            x_c = nw - VIDEO_W // 2
            
        left = x_c - VIDEO_W // 2
        right = x_c + VIDEO_W // 2
        top = nh // 2 - VIDEO_H // 2
        bottom = nh // 2 + VIDEO_H // 2
        img = img.crop((left, top, right, bottom))
    else:
        nw = VIDEO_W
        nh = int(oh * VIDEO_W / ow)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left = nw // 2 - VIDEO_W // 2
        right = nw // 2 + VIDEO_W // 2
        top = nh // 2 - VIDEO_H // 2
        bottom = nh // 2 + VIDEO_H // 2
        img = img.crop((left, top, right, bottom))
        
    return img

def generate_preview_frame(image_path, descriptions_so_far, title_data, x_offset):
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"Preview image not found: {e}")
        img = Image.new("RGB", (1920, 1080), (0, 0, 0))
        
    img = pil_resize_to_916(img, x_offset)
    
    overlay_np = make_overlay(descriptions_so_far, title_data, duration=0)
    overlay_img = Image.fromarray(overlay_np, mode="RGBA")
    
    img.paste(overlay_img, (0, 0), overlay_img)
    
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=85)
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return "data:image/jpeg;base64," + img_str


# ============================================================
# VIDEO İŞLEME
# ============================================================

def resize_to_916(clip, x_offset=0):
    ow, oh = clip.size
    if ow / oh > VIDEO_W / VIDEO_H:
        nh = VIDEO_H
        nw = int(ow * VIDEO_H / oh)
        clip = clip.resized((nw, nh))
        
        try:
            x_offset = int(x_offset)
        except Exception:
            x_offset = 0

        x_c = nw // 2 + x_offset
        if x_c - VIDEO_W // 2 < 0:
            x_c = VIDEO_W // 2
        elif x_c + VIDEO_W // 2 > nw:
            x_c = nw - VIDEO_W // 2
            
        clip = clip.cropped(x_center=x_c, y_center=VIDEO_H // 2,
                            width=VIDEO_W, height=VIDEO_H)
    else:
        nw = VIDEO_W
        nh = int(oh * VIDEO_W / ow)
        clip = clip.resized((nw, nh))
        clip = clip.cropped(x_center=VIDEO_W // 2, y_center=nh // 2,
                            width=VIDEO_W, height=VIDEO_H)
    return clip


def title_to_filename(title_line2):
    clean = re.sub(r"[^\w\s]", "", title_line2).strip().lower()
    return re.sub(r"\s+", "_", clean)


def create_ranking_video():
    if not os.path.exists(CLIP_FOLDER):
        print(f"HATA: Klasör bulunamadı: {CLIP_FOLDER}")
        return

    print(f"\n  📊 Başlangıç RAM: {_get_memory_mb():.1f} MB")

    render_data_path = os.path.join(CLIP_FOLDER, "render_data.json")
    try:
        with open(render_data_path, "r", encoding="utf-8") as f:
            render_data = json.load(f)
    except Exception as e:
        print(f"  HATA: render_data.json okunamadı: {e}")
        return

    title_data = render_data.get("title_data", {})
    clips_data = render_data.get("clips_data", [])

    print(f"\n{'='*45}")
    print(f"  ✓ Video başlığı: '{title_data.get('title_line2')}'")

    descriptions = []
    processed    = []

    for i in range(TOTAL_CLIPS, 0, -1):
        path = os.path.join(CLIP_FOLDER, f"{i}.mp4")
        if not os.path.exists(path):
            print(f"UYARI: {i}.mp4 bulunamadı, atlanıyor.")
            continue

        print(f"\n{'='*45}")
        print(f"  Klip {i} işleniyor... (RAM: {_get_memory_mb():.1f} MB)")

        data_idx = 5 - i
        if data_idx < len(clips_data):
            desc = clips_data[data_idx].get("description", "Pending Analysis")
            x_offset = clips_data[data_idx].get("x_offset", 0)
        else:
            desc = "Pending Analysis"
            x_offset = 0

        print(f"  ✓ Açıklama: {desc} (Offset: {x_offset})")
        descriptions.append((i, desc))

        clip = VideoFileClip(path)

        if clip.audio is not None:
            clip = clip.with_effects([afx.AudioNormalize()]).with_volume_scaled(0.3)

        clip = resize_to_916(clip, x_offset=x_offset)

        td = title_data or {
            "title_line1": "Ranking the",
            "title_line2": "Funniest Real Fails",
            "title_line3": "(wait for it 😱)"
        }
        overlay_arr  = make_overlay(descriptions, td, clip.duration)
        overlay_clip = ImageClip(overlay_arr, duration=clip.duration)
        final_clip   = CompositeVideoClip([clip, overlay_clip], size=(VIDEO_W, VIDEO_H))

        if i < TOTAL_CLIPS:
            final_clip = final_clip.with_effects([vfx.CrossFadeIn(0.5)])

        processed.append(final_clip)

        del overlay_arr
        overlay_clip = None
        gc.collect()
        print(f"  🧹 Klip {i} işlendi, RAM: {_get_memory_mb():.1f} MB")

    if not processed:
        print("HATA: Hiçbir klip işlenemedi!")
        return

    td       = title_data or {"title_line2": "funniest_real_fails"}
    out_name = "ranking_" + title_to_filename(td.get("title_line2", "fails")) + ".mp4"
    out_path = os.path.join(CLIP_FOLDER, out_name)

    print(f"\n{'='*45}")
    print(f"Final video birleştiriliyor → {out_name}")
    print("(2-5 dk sürebilir...)\n")

    final_video = concatenate_videoclips(processed, padding=-0.5, method="compose")

    # Müzik ekleme (qkthr.mp3)
    music_path = os.path.join(BASE_DIR, "qkthr.mp3")
    if os.path.exists(music_path):
        print(f"  🎵 Arkaplan müziği ekleniyor: {music_path}")
        try:
            bg_music = AudioFileClip(music_path)
            # Eğer müzik videodan kısaysa döngüye al (looping)
            if bg_music.duration < final_video.duration:
                bg_music = bg_music.with_effects([afx.AudioLoop(duration=final_video.duration)])
            else:
                bg_music = bg_music.subclipped(0, final_video.duration)
            
            # Müziğin sesini belirle (1.0 = orijinal)
            bg_music = bg_music.with_volume_scaled(1.0)
            
            # Videonun kendi sesiyle miksle
            if final_video.audio is not None:
                new_audio = CompositeAudioClip([final_video.audio, bg_music])
            else:
                new_audio = bg_music
                
            final_video = final_video.with_audio(new_audio)
        except Exception as e:
            print(f"  ❌ Müzik eklenirken hata oluştu: {e}")
    else:
        print(f"  ⚠️ Arkaplan müziği bulunamadı: Lütfen {music_path} yoluna mp3 dosyasını ekleyin.")
    final_video.write_videofile(
        out_path, fps=30, codec="libx264",
        audio=True,           # ses açık
        audio_codec="aac",    # ses codec
        threads=4, preset="fast"
    )

    # ── Kapsamlı Kaynak Temizliği ──────────────────────────
    print(f"  🧹 Bellek temizleniyor... (Render öncesi RAM: {_get_memory_mb():.1f} MB)")

    # 1) Final video kapat
    try:
        final_video.close()
    except Exception:
        pass

    # 2) İşlenmiş tüm klipleri kapat
    for pc in processed:
        try:
            pc.close()
        except Exception:
            pass
    processed.clear()

    # 3) Müzik klibini kapat
    if 'bg_music' in locals():
        try:
            bg_music.close()
        except Exception:
            pass

    # 4) Geçici dosyaları temizle
    if os.path.exists(TEMP_FRAME):
        try:
            os.remove(TEMP_FRAME)
        except Exception:
            pass

    # 5) Garbage collector'ı zorla
    gc.collect()

    print(f"  ✅ Bellek temizlendi. Son RAM: {_get_memory_mb():.1f} MB")
    print(f"\n✅ BİTTİ!  →  {out_path}")

if __name__ == "__main__":
    try:
        create_ranking_video()
    except Exception as e:
        print(f"\n❌ KRİTİK RENDER HATASI: {e}")
        import traceback
        traceback.print_exc()