from __future__ import annotations

import os
from pathlib import Path

import pytest

from messaging.transcription import transcribe_audio
from smoke.lib.config import SmokeConfig
from smoke.lib.e2e import VoiceFixtureDriver

pytestmark = [pytest.mark.live]


@pytest.mark.smoke_target("voice")
def test_voice_local_backend_e2e(smoke_config: SmokeConfig, tmp_path: Path) -> None:
    voice_note_enabled = bool(
        getattr(smoke_config.settings, "voice_note_enabled", False)
    )
    whisper_model = getattr(smoke_config.settings, "whisper_model", "base")
    whisper_device = getattr(smoke_config.settings, "whisper_device", "cpu")
    if not voice_note_enabled:
        pytest.skip("missing_env: VOICE_NOTE_ENABLED is false")
    if os.getenv("FCC_SMOKE_RUN_VOICE") != "1":
        pytest.skip("missing_env: set FCC_SMOKE_RUN_VOICE=1 to run voice product smoke")
    if whisper_device not in {"cpu", "cuda"}:
        pytest.skip("missing_env: WHISPER_DEVICE must be cpu or cuda")

    wav_path = tmp_path / "voice-local-product.wav"
    VoiceFixtureDriver.write_tone_wav(wav_path)
    try:
        text = transcribe_audio(
            wav_path,
            "audio/wav",
            whisper_model=whisper_model,
            whisper_device=whisper_device,
        )
    except ImportError as exc:
        pytest.skip(f"missing_env: {exc}")

    assert isinstance(text, str)
    assert text.strip()


@pytest.mark.smoke_target("voice")
def test_voice_nim_backend_e2e(smoke_config: SmokeConfig, tmp_path: Path) -> None:
    voice_note_enabled = bool(
        getattr(smoke_config.settings, "voice_note_enabled", False)
    )
    whisper_model = getattr(smoke_config.settings, "whisper_model", "base")
    whisper_device = getattr(smoke_config.settings, "whisper_device", "cpu")
    if not voice_note_enabled:
        pytest.skip("missing_env: VOICE_NOTE_ENABLED is false")
    if os.getenv("FCC_SMOKE_RUN_VOICE") != "1":
        pytest.skip("missing_env: set FCC_SMOKE_RUN_VOICE=1 to run voice product smoke")
    if whisper_device != "nvidia_nim":
        pytest.skip("missing_env: WHISPER_DEVICE must be nvidia_nim")
    if not smoke_config.settings.nvidia_nim_api_key.strip():
        pytest.skip("missing_env: NVIDIA_NIM_API_KEY is required")

    wav_path = tmp_path / "voice-nim-product.wav"
    VoiceFixtureDriver.write_tone_wav(wav_path)
    text = transcribe_audio(
        wav_path,
        "audio/wav",
        whisper_model=whisper_model,
        whisper_device="nvidia_nim",
        nvidia_nim_api_key=smoke_config.settings.nvidia_nim_api_key,
    )

    assert isinstance(text, str)
    assert text.strip()
