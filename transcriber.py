import subprocess
import re
import tempfile
import os
from pathlib import Path
from config import WHISPER_BIN, MODEL_PATH


def _convert_ogg_to_wav(ogg_path: str) -> str | None:
    """Convert ogg to 16kHz mono wav using ffmpeg."""
    wav_path = ogg_path.rsplit(".", 1)[0] + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if Path(wav_path).exists():
            return wav_path
    except Exception as e:
        print(f"ffmpeg conversion error: {e}")
    return None


def transcribe(audio_path: str) -> str:
    """
    Transcribe an audio file using whisper-cli.

    Converts to wav first (whisper-cli works best with wav), then runs
    transcription with language auto-detection.

    Returns the transcribed text as a string, or None on error.
    """
    # Convert to wav if needed
    wav_path = None
    if audio_path.endswith(".ogg"):
        wav_path = _convert_ogg_to_wav(audio_path)
        if not wav_path:
            return None
        input_path = wav_path
    else:
        input_path = audio_path

    cmd = [
        WHISPER_BIN,
        "-m", str(MODEL_PATH),
        "-f", input_path,
        "-l", "auto",
        "--no-timestamps",
        "--output-txt",
        "-ng",  # no GPU — server has no CUDA
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Try reading from .txt file first (whisper writes output there)
        txt_path = input_path.rsplit(".", 1)[0] + ".txt"
        text = None
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except FileNotFoundError:
            pass

        # Fallback: stdout
        if not text:
            text = result.stdout.strip()

        # Fallback: stderr sometimes contains the transcription
        if not text and result.stderr:
            # whisper prints to stderr in some configurations
            for line in result.stderr.split("\n"):
                line = line.strip()
                if line and not line.startswith("whisper_") and not line.startswith("ggml_") and not line.startswith("load_") and not line.startswith("system_info"):
                    text = line
                    break

        if result.returncode != 0 and not text:
            print(f"whisper error: {result.stderr[:500]}")
            return None

        return text if text else None

    except subprocess.TimeoutExpired:
        print("whisper transcription timed out")
        return None
    except FileNotFoundError:
        print(f"whisper-cli not found at {WHISPER_BIN}")
        return None
    finally:
        # Clean up converted wav file (keep original ogg)
        if wav_path and Path(wav_path).exists():
            try:
                os.remove(wav_path)
            except OSError:
                pass
            # Also remove any whisper output .txt files for the wav
            txt_path = wav_path.rsplit(".", 1)[0] + ".txt"
            if Path(txt_path).exists():
                try:
                    os.remove(txt_path)
                except OSError:
                    pass


def parse_question_number(text: str) -> int | None:
    """
    Try to extract question number from the beginning of transcribed text.
    Examples: "Вопрос 5 ...", "5. ...", "question 5 ..."
    """
    if not text:
        return None

    text_stripped = text.strip().lower()

    patterns = [
        r"^(?:вопрос|question|pytanie)\s*(\d{1,2})",
        r"^(\d{1,2})[\.\)\s]",
        r"^номер\s*(\d{1,2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text_stripped)
        if match:
            num = int(match.group(1))
            if 1 <= num <= 45:
                return num

    return None
