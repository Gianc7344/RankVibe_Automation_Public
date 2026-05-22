from moviepy import AudioFileClip

bg_music = AudioFileClip(r"c:\Users\proog\OneDrive\Masaüstü\RankVibe_Automation\qkthr.mp3")
print("Has subclip?", hasattr(bg_music, 'subclip'))
print("Has subclipped?", hasattr(bg_music, 'subclipped'))
print("Has with_section_cut_out?", hasattr(bg_music, 'with_section_cut_out'))
