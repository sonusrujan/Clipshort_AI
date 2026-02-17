import os
import glob
import shutil
import subprocess
import json
from pathlib import Path
from typing import List, Dict


# --- CONFIG ---
MOVIE_DIR = 'movies'
SRT_DIR = 'scripts/srt_files'
SCRIPT_DIR = 'scripts'
OLLAMA_DIR = 'ollama'
KOKORO_DIR = 'kokoro-tts'
CLIPS_DIR = 'clips'
OUTPUT_DIR = 'output'
TIKTOK_DIR = 'tiktok_output'
RETIRED_DIR = 'movies_retired'
MUSIC_DIR = 'music'

# --- UTILS ---
def find_movie_file() -> str:
    files = glob.glob(os.path.join(MOVIE_DIR, '*.mp4')) + glob.glob(os.path.join(MOVIE_DIR, '*.mkv'))
    if not files:
        raise FileNotFoundError('No .mp4 or .mkv file found in movies/.')
    return files[0]

def fetch_srt(movie_path: str) -> str:
    # Look for SRT in SRT_DIR, else extract from video, else try to fetch from OpenSubtitles
    import requests
    basename = Path(movie_path).stem
    srt_path = os.path.join(SRT_DIR, f'{basename}.srt')
    if os.path.exists(srt_path):
        return srt_path
    # Try to extract subtitles from video using ffmpeg
    print(f"SRT not found locally for {basename}, attempting to extract from video...")
    import subprocess
    extract_cmd = [
        'ffmpeg', '-y', '-i', movie_path, '-map', '0:s:0', srt_path
    ]
    result = subprocess.run(extract_cmd, capture_output=True)
    if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
        print(f"Extracted subtitles to {srt_path}")
        return srt_path
    # Try to fetch from OpenSubtitles (placeholder logic)
    print(f"Subtitle extraction failed, attempting to download...")
    api_key = os.environ.get('OPENSUBTITLES_API_KEY')
    if not api_key:
        raise FileNotFoundError(f'SRT not found for {basename}, could not extract from video, and no OpenSubtitles API key set.')
    # This is a placeholder for actual API integration
    # You would use requests to call the OpenSubtitles API and download the SRT
    # For now, just raise error
    raise FileNotFoundError(f'SRT not found for {basename}, could not extract from video, and download not implemented.')

def fetch_script(movie_path: str) -> str:
    # Optional: try to fetch script for extra context
    # Placeholder: try to find script in scripts/ by basename
    basename = Path(movie_path).stem
    script_path = os.path.join(SCRIPT_DIR, f'{basename}.txt')
    if os.path.exists(script_path):
        return script_path
    # TODO: Implement actual script fetching from IMSDb or similar
    print(f"Script not found for {basename}, skipping script context.")
    return ''

## Removed old call_ollama_for_plan signature (was left in by mistake)
def call_ollama_for_plan(srt_path: str) -> List[Dict]:
    import os
    import json
    import requests
    from dotenv import load_dotenv
    load_dotenv()
    if os.path.exists("plan.json"):
        with open("plan.json", "r") as f:
            return json.load(f)
    # Use Gemini API to generate plan if plan.json does not exist
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set in .env file")
    with open(srt_path, "r") as srt_file:
        srt_content = srt_file.read()
    gemini_prompt = f"Generate a JSON plan for video cutting based on the following SRT subtitles. The plan should be a list of objects with 'start', 'end', and 'narration' fields.\n\nSRT:\n{srt_content}"
    gemini_headers = {
        "Content-Type": "application/json"
    }
    gemini_payload = {
        "contents": [{"parts": [{"text": gemini_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 2048,
            "temperature": 0.7
        }
    }
    gemini_url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    response = requests.post(gemini_url, headers=gemini_headers, json=gemini_payload)
    if response.status_code == 200:
        gemini_response = response.json()
        # Extract the plan from the Gemini response
        try:
            plan_text = gemini_response["candidates"][0]["content"]["parts"][0]["text"]
            plan = json.loads(plan_text)
        except Exception as e:
            print(f"Error parsing Gemini response: {e}\nRaw response: {gemini_response}")
            raise FileNotFoundError("plan.json not found and Gemini API call failed (invalid response format).")
        with open("plan.json", "w") as f:
            json.dump(plan, f, indent=2)
        return plan
    else:
        print(f"Gemini API error: {response.status_code} {response.text}")
        raise FileNotFoundError("plan.json not found and Gemini API call failed.")

def generate_voiceover(narration: str, idx: int) -> str:
    out_path = f'{CLIPS_DIR}/voiceover_{idx}.wav'
    import subprocess
    # Write narration to a temp file
    import tempfile
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as f:
        f.write(narration)
        text_path = f.name
    try:
        result = subprocess.run([
            'kokoro-tts', text_path, out_path, '--voice', 'af_sarah', '--lang', 'en-us', '--speed', '1.1', '--model', './kokoro-v1.0.onnx', '--voices', './voices-v1.0.bin'
        ], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"kokoro-tts error: {result.stderr}")
    except Exception as e:
        print(f"kokoro-tts call failed: {e}")
    finally:
        os.remove(text_path)
    return out_path

def cut_and_stretch_clip(movie_path: str, start: float, end: float, narration_audio: str, idx: int) -> str:
    out_path = f'{CLIPS_DIR}/clip_{idx}.mp4'
    # Improved: Use ffprobe for accurate durations and FFmpeg filters for precise sync
    import contextlib
    import wave
    import shlex
    # Get narration audio duration using ffprobe for accuracy
    def get_audio_duration(path):
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', path
            ], capture_output=True, text=True)
            return float(result.stdout.strip())
        except Exception as e:
            print(f"Could not get audio duration for {path}: {e}")
            return None

    audio_duration = get_audio_duration(narration_audio)
    video_duration = end - start
    print(f"[DEBUG] Clip {idx}: audio_duration={audio_duration:.3f}, video_duration={video_duration:.3f}")

    # Use the original narration audio as-is (no speed/duration adjustment)
    narration_audio_to_use = narration_audio

    # Use video segment duration, combine with stretched audio
    # 9:6 aspect ratio: width = ih*9/6 = ih*1.5, height = ih
    # True vertical 9:16 crop: crop height from width, then scale to 720x1280
    combine_cmd = [
        'ffmpeg', '-y',
        '-ss', str(start), '-t', str(video_duration), '-i', movie_path,
        '-i', narration_audio_to_use,
        '-filter_complex', '[0:v]crop=ih*9/16:ih,scale=720:1280,zoompan=z=1.05:x=iw/2-(iw/zoom/2):y=ih/2-(ih/zoom/2):d=1:s=720x1280,hflip[v]',
        '-map', '[v]',
        '-map', '1:a',
        '-c:v', 'h264_videotoolbox',
        '-b:v', '6000k',
        out_path
    ]
    subprocess.run(combine_cmd)
    # No stretched audio to remove
    return out_path

def mix_background_music(clip_paths: List[str]) -> List[str]:
    # Mix background music if available
    import random
    import subprocess
    music_files = glob.glob(os.path.join(MUSIC_DIR, '*.mp3'))
    if not music_files:
        return clip_paths
    mixed_clips = []
    for idx, clip in enumerate(clip_paths):
        music = random.choice(music_files)
        out_path = f'{CLIPS_DIR}/mixed_{idx}.mp4'
        # FFmpeg: mix music (skip first 10s of music, match duration)
        cmd = [
            'ffmpeg', '-y', '-i', clip, '-ss', '10', '-i', music,
            '-filter_complex', '[1:a]volume=0.15[a1];[0:a][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]',
            '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-shortest', out_path
        ]
        subprocess.run(cmd, capture_output=True)
        mixed_clips.append(out_path)
    return mixed_clips

def concatenate_clips(clip_paths: List[str], output_path: str):
    # Use FFmpeg to concatenate clips
    import subprocess
    import tempfile
    # Create a temporary file list for FFmpeg
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as f:
        for clip in clip_paths:
            f.write(f"file '{os.path.abspath(clip)}'\n")
        filelist = f.name
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', filelist, '-c', 'copy', output_path
    ]
    subprocess.run(cmd, capture_output=True)
    os.remove(filelist)

def export_vertical(standard_path: str, vertical_path: str):
    # Use FFmpeg to crop/resize for TikTok (9:16)
    import subprocess
    # Get video dimensions
    probe_cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
        'stream=width,height', '-of', 'csv=s=x:p=0', standard_path
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffprobe error: {result.stderr}")
        return
    width, height = map(int, result.stdout.strip().split('x'))
    # Calculate crop for 9:16
    new_height = height
    new_width = int(new_height * 9 / 16)
    if new_width > width:
        new_width = width
        new_height = int(new_width * 16 / 9)
    x = (width - new_width) // 2
    y = (height - new_height) // 2
    crop_filter = f"crop={new_width}:{new_height}:{x}:{y},scale=720:1280"
    cmd = [
        'ffmpeg', '-y', '-i', standard_path, '-vf', crop_filter, '-c:a', 'copy', vertical_path
    ]
    subprocess.run(cmd, capture_output=True)

def cleanup(movie_path: str):
    # Move processed movie to retired
    os.makedirs(RETIRED_DIR, exist_ok=True)
    shutil.move(movie_path, os.path.join(RETIRED_DIR, os.path.basename(movie_path)))
    # Clear temp clips
    for f in glob.glob(os.path.join(CLIPS_DIR, '*')):
        os.remove(f)

def main():
    movie_path = find_movie_file()
    srt_path = fetch_srt(movie_path)
    plan = call_ollama_for_plan(srt_path)
    if not plan:
        print('No clip plan generated.')
        return
    clip_paths = []
    for idx, clip in enumerate(plan):
        out_path = f'{CLIPS_DIR}/clip_{idx}.mp4'
        if os.path.exists(out_path):
            print(f"Clip {idx}: Already exists, skipping generation.")
            clip_paths.append(out_path)
            continue
        try:
            narration = clip.get('narration') or clip.get('detailed narration') or ''
            if not narration:
                print(f"Clip {idx}: No narration found, skipping.")
                continue
            narration_audio = generate_voiceover(narration, idx)
            clip_path = cut_and_stretch_clip(movie_path, clip['start'], clip['end'], narration_audio, idx)
            clip_paths.append(clip_path)
            print(f"Clip {idx}: Success.")
        except Exception as e:
            print(f"Clip {idx}: Failed - {e}")
    clip_paths = mix_background_music(clip_paths)
    movie_title = Path(movie_path).stem
    output_path = os.path.join(OUTPUT_DIR, f'{movie_title}.mp4')
    concatenate_clips(clip_paths, output_path)
    # Export each clip as a separate vertical TikTok video
    os.makedirs(TIKTOK_DIR, exist_ok=True)
    for idx, clip_path in enumerate(clip_paths):
        vertical_clip_path = os.path.join(TIKTOK_DIR, f'{idx+1}.mp4')
        if os.path.exists(vertical_clip_path):
            print(f"TikTok video {idx+1}.mp4 already exists, skipping export.")
            continue
        export_vertical(clip_path, vertical_clip_path)
    cleanup(movie_path)
    print(f'Exported: {output_path} and {TIKTOK_DIR}/[clips]')

if __name__ == '__main__':
    main()
