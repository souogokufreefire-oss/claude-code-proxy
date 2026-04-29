from __future__ import annotations

import math
import os
import wave
from pathlib import Path

import pytest

from messaging.transcription import transcribe_audio
from smoke.lib.config import SmokeConfig

pytestmark = [pytest.mark.live, pytest.mark.smoke_target("voice")]


def test_voice_transcription_backend_when_explicitly_enabled(
    smoke_config: SmokeConfig, tmp_path: Path
) -> None:
    voice_note_enabled = bool(
        getattr(smoke_config.settings, "voice_note_enabled", False)
    )
    whisper_model = getattr(smoke_config.settings, "whisper_model", "base")
    whisper_device = getattr(smoke_config.settings, "whisper_device", "cpu")
    if not voice_note_enabled:
        pytest.skip("VOICE_NOTE_ENABLED is false")
    if os.getenv("FCC_SMOKE_RUN_VOICE") != "1":
        pytest.skip("set FCC_SMOKE_RUN_VOICE=1 to run transcription smoke")

    wav_path = tmp_path / "smoke-tone.wav"
    _write_tone_wav(wav_path)
    try:
        t_kw: dict[str, str] = {
            "whisper_model": whisper_model,
            "whisper_device": whisper_device,
        }
        if whisper_device == "nvidia_nim":
            t_kw["nvidia_nim_api_key"] = smoke_config.settings.nvidia_nim_api_key
        text = transcribe_audio(wav_path, "audio/wav", **t_kw)
    except ImportError as exc:
        pytest.skip(str(exc))
    assert isinstance(text, str)
    assert text.strip()


def _write_tone_wav(path: Path) -> None:
    sample_rate = 16000
    duration_s = 0.25
    amplitude = 8000
    frames = bytearray()
    for i in range(int(sample_rate * duration_s)):
        sample = int(amplitude * math.sin(2 * math.pi * 440 * i / sample_rate))
        frames.extend(sample.to_bytes(2, byteorder="little", signed=True))

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
