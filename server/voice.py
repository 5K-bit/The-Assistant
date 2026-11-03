"""Voice adapters.

Speech in and speech out, behind the same kind of adapter interface the
engine uses: nothing here names a particular STT or TTS program, and the
operator supplies the exact command line.

STT adapters:

- ``none``    — no transcription. The default, so the microphone stays
                unused until the operator turns it on.
- ``command`` — any transcriber driven from a configured argv template.

TTS adapters:

- ``none``    — no speech out. The default.
- ``command`` — any synthesiser driven from a configured argv template,
                returning WAV bytes.
- ``browser`` — the HUD speaks through the browser's own on-device
                voices. The server synthesises nothing in this mode and
                says so, rather than reporting a capability it lacks.

Why argv templates rather than named integrations: whisper.cpp,
openai-whisper, piper, `say` and espeak-ng all take different flags, and
a wrong guess fails at the worst moment. The operator gives the command
once; README carries working recipes.

An adapter returns a real result or raises VoiceError. A transcript is
never invented, and a failed run is reported as failed.
"""

import re
import subprocess
import tempfile
from pathlib import Path

DEFAULT_STT_TIMEOUT = 120
DEFAULT_TTS_TIMEOUT = 60

# Both whisper.cpp and openai-whisper prefix each segment with its time
# range. The HUD wants the words, so strip the range and keep the text.
TIMESTAMP = re.compile(r"^\s*\[[\d:.,]+\s*-+>\s*[\d:.,]+\]\s*")

# A transcriber is handed a file path and will open whatever is there, so
# check the container before the subprocess runs rather than after.
WAV_MAGIC = (b"RIFF", b"WAVE")


class VoiceError(RuntimeError):
    """Speech in or out could not be done, and was not faked."""


def is_wav(data):
    """True when these bytes are a RIFF/WAVE container."""
    return len(data) > 12 and data[0:4] == WAV_MAGIC[0] and data[8:12] == WAV_MAGIC[1]


def clean_transcript(text, strip_timestamps=True):
    """Collapse a transcriber's output into one line of speech."""
    lines = []
    for line in (text or "").splitlines():
        if strip_timestamps:
            line = TIMESTAMP.sub("", line)
        line = line.strip()
        # whisper.cpp writes progress and model notes to stdout too; a
        # bracketed-only line carries no speech.
        if line and not (line.startswith("[") and line.endswith("]")):
            lines.append(line)
    return " ".join(lines).strip()


def _run(argv, stdin=None, timeout=60, label="command"):
    """Run a local program, returning raw stdout. Never through a shell."""
    try:
        result = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VoiceError(f"{label} not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VoiceError(f"{label} timed out after {timeout}s") from exc
    except OSError as exc:
        raise VoiceError(f"{label} failed to start: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or b"").decode("utf-8", "replace").strip()[:400]
        raise VoiceError(f"{label} exited {result.returncode}: {detail}")
    return result.stdout or b""


# --- speech in --------------------------------------------------------

class SttNone:
    """Captures nothing, transcribes nothing."""

    name = "none"
    available = False

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def describe(self):
        return "transcription disabled"

    def transcribe(self, audio):
        raise VoiceError("transcription is disabled; set voice.stt.enabled to true")


class SttCommand:
    """Any transcriber, driven by a configured argv template.

    ``{audio}`` in the argv is replaced with the path of the recorded
    WAV; without it the audio goes to the process on stdin, for tools
    that read a stream. ``{output}`` is replaced with a path the tool may
    write the transcript to, and is read back in preference to stdout.
    The command is never run through a shell.
    """

    name = "command"
    available = True

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.argv = list(self.cfg.get("command") or [])
        self.timeout = int(self.cfg.get("timeout_seconds", DEFAULT_STT_TIMEOUT))
        self.strip_timestamps = self.cfg.get("strip_timestamps", True)
        self.cwd = self.cfg.get("cwd") or None

    def describe(self):
        return f"command {' '.join(self.argv) if self.argv else '(unset)'}"

    def transcribe(self, audio):
        if not self.argv:
            raise VoiceError(
                "no transcriber configured; set voice.stt.command to the argv "
                "of your speech-to-text tool"
            )
        if not is_wav(audio):
            raise VoiceError("recording was not a WAV container; refusing to run the transcriber")

        with tempfile.TemporaryDirectory(prefix="assistant-stt-") as work:
            clip = Path(work) / "clip.wav"
            clip.write_bytes(audio)
            transcript_file = Path(work) / "transcript.txt"
            argv = []
            for part in self.argv:
                if part == "{audio}":
                    argv.append(str(clip))
                elif part == "{output}":
                    argv.append(str(transcript_file))
                else:
                    argv.append(part)
            stdin = None if "{audio}" in self.argv else audio
            stdout = _run(argv, stdin, self.timeout, "transcriber")

            raw = stdout.decode("utf-8", "replace")
            if "{output}" in self.argv:
                # Some tools append their own extension to the given stem.
                written = [transcript_file] + sorted(
                    p for p in transcript_file.parent.glob("transcript.*") if p.is_file()
                )
                for candidate in written:
                    if candidate.is_file():
                        text = candidate.read_text(encoding="utf-8", errors="replace")
                        if text.strip():
                            raw = text
                            break

        text = clean_transcript(raw, self.strip_timestamps)
        if not text:
            raise VoiceError("transcriber returned no speech")
        return text


# --- speech out -------------------------------------------------------

class TtsNone:
    """Says nothing."""

    name = "none"
    available = False
    server_side = True

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def describe(self):
        return "speech disabled"

    def speak(self, text):
        raise VoiceError("speech is disabled; set voice.tts.enabled to true")


class TtsBrowser:
    """The HUD speaks, using the browser's own on-device voices.

    The server synthesises nothing here. It reports the mode so the HUD
    knows to do the work, and refuses a synthesis request rather than
    returning silence that would look like success.
    """

    name = "browser"
    available = True
    server_side = False

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def describe(self):
        return "browser speech synthesis, on-device voices only"

    def speak(self, text):
        raise VoiceError("this mode speaks in the browser; the server does not synthesise")


class TtsCommand:
    """Any synthesiser, driven by a configured argv template.

    ``{text}`` in the argv is replaced with the line to speak; without it
    the text goes to the process on stdin. ``{output}`` is replaced with
    a path for the tool to write WAV to, and is read back in preference
    to stdout. The command is never run through a shell.
    """

    name = "command"
    available = True
    server_side = True

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.argv = list(self.cfg.get("command") or [])
        self.timeout = int(self.cfg.get("timeout_seconds", DEFAULT_TTS_TIMEOUT))
        self.content_type = self.cfg.get("content_type", "audio/wav")
        self.cwd = self.cfg.get("cwd") or None

    def describe(self):
        return f"command {' '.join(self.argv) if self.argv else '(unset)'}"

    def speak(self, text):
        if not self.argv:
            raise VoiceError(
                "no synthesiser configured; set voice.tts.command to the argv "
                "of your text-to-speech tool"
            )
        line = (text or "").strip()
        if not line:
            raise VoiceError("nothing to speak")

        with tempfile.TemporaryDirectory(prefix="assistant-tts-") as work:
            out = Path(work) / "speech.wav"
            argv = [
                str(out) if part == "{output}" else (line if part == "{text}" else part)
                for part in self.argv
            ]
            stdin = None if "{text}" in self.argv else line.encode("utf-8")
            stdout = _run(argv, stdin, self.timeout, "synthesiser")
            audio = out.read_bytes() if ("{output}" in self.argv and out.is_file()) else stdout

        if not audio:
            raise VoiceError("synthesiser produced no audio")
        return audio, self.content_type


STT_ADAPTERS = {"none": SttNone, "command": SttCommand}
TTS_ADAPTERS = {"none": TtsNone, "command": TtsCommand, "browser": TtsBrowser}


def _build(cfg, adapters, kind):
    settings = cfg or {}
    if not settings.get("enabled"):
        return adapters["none"](settings)
    name = str(settings.get("adapter", "none")).lower()
    adapter = adapters.get(name)
    if adapter is None:
        raise VoiceError(
            f"unknown {kind} adapter '{name}'; known: {', '.join(sorted(adapters))}"
        )
    return adapter(settings)


def build_stt(voice_cfg):
    """Return the speech-to-text adapter named by config."""
    return _build((voice_cfg or {}).get("stt"), STT_ADAPTERS, "stt")


def build_tts(voice_cfg):
    """Return the text-to-speech adapter named by config."""
    return _build((voice_cfg or {}).get("tts"), TTS_ADAPTERS, "tts")


def state(stt, tts, voice_cfg=None):
    """What the HUD needs to know, with no filesystem paths in it."""
    settings = (voice_cfg or {}).get("tts") or {}
    return {
        "stt": {"enabled": stt.available, "adapter": stt.name},
        "tts": {
            "enabled": tts.available,
            "adapter": tts.name,
            # "server" means the server returns audio; "browser" means the
            # HUD must synthesise locally; "off" means neither.
            "mode": ("server" if tts.server_side else "browser") if tts.available else "off",
            "speak_replies": bool(tts.available and settings.get("speak_replies", True)),
        },
    }
