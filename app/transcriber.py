import os
from typing import Optional, Dict, Any, List

import requests
from dotenv import load_dotenv


class ElevenLabsTranscriber:
    """Handles audio-to-text conversion via ElevenLabs API."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        language_code: Optional[str] = None,
        diarize: bool = False,
        tag_audio_events: bool = False,
    ) -> None:
        # Load local dotenv files if available
        load_dotenv(".env.local", override=False)
        load_dotenv(override=False)

        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.model_id = model_id or os.getenv("ELEVENLABS_MODEL_ID", "scribe_v1")
        self.language_code = language_code or os.getenv("ELEVENLABS_LANGUAGE_CODE")
        self.diarize = diarize or os.getenv("ELEVENLABS_DIARIZE", "false").lower() == "true"
        self.tag_audio_events = (
            tag_audio_events or os.getenv("ELEVENLABS_TAG_AUDIO_EVENTS", "false").lower() == "true"
        )

    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        """Send the audio file to ElevenLabs and return transcription info."""
        if not self.api_key:
            return {
                "status": "skipped",
                "text": None,
                "segments": [],
                "error": "ELEVENLABS_API_KEY not configured",
            }

        if not os.path.exists(audio_path):
            return {
                "status": "failed",
                "text": None,
                "segments": [],
                "error": f"Audio file not found: {audio_path}",
            }

        files = {"file": open(audio_path, "rb")}
        data = {"model_id": self.model_id}

        if self.language_code:
            data["language_code"] = self.language_code
        if self.diarize:
            data["diarize"] = "true"
        if self.tag_audio_events:
            data["tag_audio_events"] = "true"

        try:
            response = requests.post(
                "https://api.elevenlabs.io/v1/speech-to-text",
                headers={"xi-api-key": self.api_key},
                data=data,
                files={"file": files["file"]},
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            segments = self._extract_segments(payload)
            return {
                "status": "completed",
                "text": payload.get("text"),
                "segments": segments,
                "error": None,
            }
        except requests.RequestException as exc:
            error_msg = str(exc)
            if exc.response is not None:
                try:
                    details = exc.response.json()
                    error_msg = details.get("detail") or details.get("error") or error_msg
                except ValueError:
                    error_msg = exc.response.text or error_msg
            return {
                "status": "failed",
                "text": None,
                "segments": [],
                "error": error_msg,
            }
        finally:
            files["file"].close()

    def _extract_segments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Normalize the ElevenLabs word-level timestamps into a structure
        we can persist. Each item contains the token text plus millisecond
        offsets that downstream search/chunking can use.
        """
        words_source = payload.get("words") or payload.get("word_timestamps") or []

        if isinstance(words_source, dict):
            # Some responses may wrap words in a dict keyed by channel/speaker.
            # Flatten into a plain list.
            flattened: List[Any] = []
            for value in words_source.values():
                if isinstance(value, list):
                    flattened.extend(value)
            words_source = flattened

        segments: List[Dict[str, Any]] = []
        if not isinstance(words_source, list):
            return segments

        for entry in words_source:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text") or entry.get("word")
            if not text:
                continue

            start_ms = self._to_milliseconds(
                seconds_value=entry.get("start") or entry.get("start_time"),
                milliseconds_value=entry.get("start_ms"),
            )
            end_ms = self._to_milliseconds(
                seconds_value=entry.get("end") or entry.get("end_time"),
                milliseconds_value=entry.get("end_ms"),
            )

            segment = {
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "confidence": entry.get("confidence"),
                "speaker": entry.get("speaker"),
            }
            # Preserve diarization tags/events if present.
            if "type" in entry:
                segment["type"] = entry["type"]
            segments.append(segment)

        return segments

    @staticmethod
    def _to_milliseconds(*, seconds_value: Optional[Any], milliseconds_value: Optional[Any]) -> Optional[int]:
        """Convert various timestamp formats to millisecond integers."""
        if milliseconds_value is not None:
            try:
                return int(float(milliseconds_value))
            except (TypeError, ValueError):
                return None
        if seconds_value is not None:
            try:
                return int(float(seconds_value) * 1000)
            except (TypeError, ValueError):
                return None
        return None
