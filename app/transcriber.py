import os
from typing import Optional, Dict

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

    def transcribe(self, audio_path: str) -> Dict[str, Optional[str]]:
        """Send the audio file to ElevenLabs and return transcription info."""
        if not self.api_key:
            return {
                "status": "skipped",
                "text": None,
                "error": "ELEVENLABS_API_KEY not configured",
            }

        if not os.path.exists(audio_path):
            return {
                "status": "failed",
                "text": None,
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
            return {
                "status": "completed",
                "text": payload.get("text"),
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
                "error": error_msg,
            }
        finally:
            files["file"].close()
