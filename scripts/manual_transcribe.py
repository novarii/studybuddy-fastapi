import argparse
import os
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.downloader import VideoDownloader  # noqa: E402
from app.storage import LocalStorage  # noqa: E402
from app.transcriber import ElevenLabsTranscriber  # noqa: E402


def _extract_audio_if_needed(downloader: VideoDownloader, media_path: Path, sample_id: str) -> Path:
    """
    Convert video files to audio so the ElevenLabs client receives a supported format.
    Audio files are returned as-is.
    """
    audio_extensions = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
    if media_path.suffix.lower() in audio_extensions:
        return media_path

    temp_audio = downloader._convert_to_audio(str(media_path), sample_id)  # type: ignore[attr-defined]
    return Path(temp_audio)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a local clip with ElevenLabs and print timestamps.")
    parser.add_argument(
        "path",
        type=Path,
        help="Path to a local audio/video file.",
    )
    parser.add_argument(
        "--video-id",
        dest="video_id",
        default="manual_test",
        help="Identifier used when generating temp files (default: manual_test).",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"File not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    storage = LocalStorage()
    transcriber = ElevenLabsTranscriber()
    downloader = VideoDownloader(storage=storage, transcriber=transcriber)

    temp_audio: Optional[Path] = None
    try:
        temp_audio = _extract_audio_if_needed(downloader, args.path, args.video_id)
        result = transcriber.transcribe(str(temp_audio))
    finally:
        if temp_audio and temp_audio != args.path and temp_audio.exists():
            temp_audio.unlink(missing_ok=True)

    print(f"Status: {result.get('status')}")
    if error := result.get("error"):
        print(f"Error: {error}")

    transcript = result.get("text") or ""
    print("Transcript Preview:")
    print(transcript[:500] + ("..." if len(transcript) > 500 else ""))

    segments = result.get("segments") or []
    print(f"Segments captured: {len(segments)}")
    for sample in segments[:5]:
        start = sample.get("start_ms")
        end = sample.get("end_ms")
        text = sample.get("text")
        print(f"- [{start}ms -> {end}ms] {text}")


if __name__ == "__main__":
    main()
