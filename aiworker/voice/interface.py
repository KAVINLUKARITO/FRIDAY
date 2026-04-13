"""Voice control interface for AIWorker."""

from __future__ import annotations

from typing import Any

try:
    import speech_recognition as sr
except Exception:  # pragma: no cover - optional dependency in test env
    sr = None

try:
    import pyaudio  # noqa: F401
except Exception:  # pragma: no cover - optional dependency in test env
    pyaudio = None


VOICE_COMMANDS = {
    "start learning": ("start-learning", {"goal": "voice-learning-session"}),
    "stop loop": ("stop-loop", {}),
    "status report": ("status-report", {}),
    "apply patch": ("apply-patch", {}),
    "rollback patch": ("rollback-patch", {}),
}


def _normalize_command(command_text: str) -> str:
    return " ".join(command_text.strip().lower().split())


def execute_voice_command(command_text: str, *, admin: bool = False) -> dict[str, Any]:
    normalized = _normalize_command(command_text)
    if normalized not in VOICE_COMMANDS:
        return {"recognized": False, "command": normalized, "error": "unsupported voice command"}

    command, kwargs = VOICE_COMMANDS[normalized]
    payload = dict(kwargs)
    if command in {"apply-patch", "rollback-patch"}:
        payload["admin"] = admin

    from aiworker.cli import execute_control_command

    result = execute_control_command(command, **payload)
    return {"recognized": True, "command": normalized, "result": result}


def _recognize_once() -> str:
    if sr is None or pyaudio is None:
        raise RuntimeError("SpeechRecognition and PyAudio must be installed for microphone input.")

    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)
    return recognizer.recognize_google(audio)


def start_voice_listener(
    *,
    once: bool = False,
    command_text: str | None = None,
    admin: bool = False,
) -> dict[str, Any] | None:
    """Listen for supported commands or process a text fallback."""
    if command_text:
        return execute_voice_command(command_text, admin=admin)

    if once:
        spoken = _recognize_once()
        return execute_voice_command(spoken, admin=admin)

    if sr is None or pyaudio is None:
        raise RuntimeError("SpeechRecognition and PyAudio must be installed for voice mode.")

    recognizer = sr.Recognizer()
    while True:  # pragma: no cover - interactive path
        with sr.Microphone() as source:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)
        transcript = recognizer.recognize_google(audio)
        result = execute_voice_command(transcript, admin=admin)
        if _normalize_command(transcript) == "stop loop":
            return result
