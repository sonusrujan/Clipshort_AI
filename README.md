
# Movie Recap Pipeline

This project automates the creation of movie recap videos with narration, subtitles, and music overlays, exporting both standard and vertical (YouTube Shorts/TikTok) formats.

## Workflow
1. **Input**: Place a movie file in `movies/`.
2. **Subtitles**: The app fetches SRT subtitles automatically (or uses cached/manual ones in `scripts/srt_files/`).
3. **Plan Generation**: If `plan.json` does not exist, the script uses the Gemini API to generate a JSON plan (list of segments with `start`, `end`, and `narration` fields) based on the SRT file. The Gemini API key is loaded from a `.env` file. If `plan.json` exists, it is loaded directly.
4. **Voiceover**: Uses kokoro-tts to generate narration audio for each clip.
5. **Clip Generation**: For each segment in the plan:
   - Skips clips that already exist for incremental processing.
   - Cuts the video segment, applies vertical 9:16 crop, scales to 720x1280, zooms 5%, and mirrors horizontally.
   - Mutes original audio and overlays the narration.
6. **Background Music**: If music files exist in `music/`, mixes them in (randomly, skipping intros, matching duration).
7. **Merging**: Concatenates all generated clips into a single output video in `output/`.
8. **Shorts/TikTok Export**: Each clip is exported as a separate vertical video in `tiktok_output/`, skipping any that already exist.
9. **Cleanup**: Moves processed movie to `movies_retired/`, clears temp files in `clips/`.

## Requirements
- Python 3.9+
- ffmpeg (system binary)
- requests
- tqdm
- srt
- numpy
- pydub
- python-dotenv
- kokoro-tts (CLI)
- Gemini API access (for plan generation)

## Setup
1. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```
2. Ensure ffmpeg and kokoro-tts are installed and available in your PATH.
3. Place your movie files in `movies/`.
4. Add your Gemini API key to a `.env` file in the project root:
   ```
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
5. Run the main pipeline script:
   ```sh
   python main.py
   ```

---

**Note:** This is a work in progress. See .github/copilot-instructions.md for development workflow and customization.
