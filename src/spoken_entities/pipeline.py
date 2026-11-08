"""TTS -> phone channel -> speech recognition -> extraction, every stage cached on disk.

    uv run python -m spoken_entities.pipeline tts        # ElevenLabs, audio/ (not committed)
    uv run python -m spoken_entities.pipeline asr        # ElevenLabs Scribe -> data/transcripts.jsonl
    uv run python -m spoken_entities.pipeline extract    # Claude -> data/extractions.jsonl
    uv run python -m spoken_entities.score               # data/ -> docs/results.md (no keys needed)

Keys come from ELEVENLABS_API_KEY / ANTHROPIC_API_KEY, or ~/.secrets/{elevenlabs,anthropic}.env.
Transcripts and extractions are committed, so the scoring reruns in CI without keys or audio.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from spoken_entities.entities import FRAMES, build_set, clip_text
from spoken_entities.italian import (
    MONTHS,
    _merge_split_numbers,
    _strip_accents,
    parse_number_word,
    to_symbols,
)

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / "audio"
DATA = ROOT / "data"

# Voices: one ElevenLabs default (English-native) voice speaking Italian, one native Italian voice
# from the public library. Named by role in the results.
VOICES = {"default-f": "EXAVITQu4vr4xnSDxMaL", "native-m": "W71zT1VwIFFx3mMGH2uZ"}
TTS_MODEL = "eleven_flash_v2_5"  # the low-latency model voice agents use
STYLES = ("natural", "spelled")
CHANNELS = ("clean", "phone", "phone_noise")
ASR_MODEL = "scribe_v1"
CLAUDE_MODELS = ["claude-haiku-5-5", "claude-opus-5-5"]


def _key(name: str, file: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    path = Path.home() / ".secrets" / f"{file}.env"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{name} not set and not in {path}")


def clips() -> list[dict[str, str]]:
    return [{"clip": f"{e.id}.{s}", "entity": e.id, "type": e.type, "value": e.value, "style": s,
             "version": e.version, "text": clip_text(e.type, e.value, s)} for e in build_set() for s in STYLES]


# --- TTS ----------------------------------------------------------------------------


def _tts(text: str, voice_id: str, out: Path, key: str) -> None:
    body = json.dumps({"text": text, "model_id": TTS_MODEL, "language_code": "it"}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_64",
        data=body, headers={"xi-api-key": key, "Content-Type": "application/json"})
    audio = urllib.request.urlopen(req, timeout=60).read()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)


def _channel(src: Path, channel: str) -> Path:
    """clean: the TTS file. phone: 8 kHz, 300-3400 Hz, G.711 mu-law. phone_noise: plus pink noise."""
    if channel == "clean":
        return src
    dst = src.with_name(f"{src.stem}.{channel}.wav")
    if dst.exists():
        return dst
    band = "aresample=8000,highpass=f=300,lowpass=f=3400"
    if channel == "phone":
        graph = ["-af", band]
    else:
        graph = ["-filter_complex",
                 f"[0:a]{band}[s];anoisesrc=color=pink:amplitude=0.02:sample_rate=8000[n];"
                 "[s][n]amix=inputs=2:duration=first:normalize=0"]
    mulaw = dst.with_suffix(".mulaw.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *graph,
                    "-ac", "1", "-ar", "8000", "-c:a", "pcm_mulaw", str(mulaw)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mulaw), "-c:a", "pcm_s16le", str(dst)], check=True)
    mulaw.unlink()
    return dst


def run_tts() -> None:
    key = _key("ELEVENLABS_API_KEY", "elevenlabs")
    jobs = [(c, v, vid) for c in clips() for v, vid in VOICES.items()
            if not (AUDIO / v / f"{c['clip']}.mp3").exists()]
    print(f"{len(jobs)} clips to synthesise, {sum(len(c['text']) for c, _, _ in jobs)} characters")

    def one(job):
        c, v, vid = job
        try:
            _tts(c["text"], vid, AUDIO / v / f"{c['clip']}.mp3", key)
            return None
        except urllib.error.HTTPError as e:
            return f"{v}/{c['clip']}: {e.code} {e.read()[:200]!r}"
        except Exception as e:  # network or timeout: retried on the next run
            return f"{v}/{c['clip']}: {type(e).__name__} {str(e)[:200]}"

    with ThreadPoolExecutor(4) as pool:
        errors = [e for e in pool.map(one, jobs) if e]
    for e in errors[:10]:
        print("TTS error", e)
    if errors:
        sys.exit(1)


# --- ASR ----------------------------------------------------------------------------


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _append(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def _scribe(path: Path, key: str) -> str:
    b = uuid.uuid4().hex
    fields = {"model_id": ASR_MODEL, "language_code": "ita", "tag_audio_events": "false"}
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    mime = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f"Content-Type: {mime}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request("https://api.elevenlabs.io/v1/speech-to-text", data=b"".join(parts),
                                 headers={"xi-api-key": key, "Content-Type": f"multipart/form-data; boundary={b}"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["text"]


def run_asr() -> None:
    key = _key("ELEVENLABS_API_KEY", "elevenlabs")
    out = DATA / "transcripts.jsonl"
    done = {(r["clip"], r["voice"], r["channel"], r["asr"]) for r in _jsonl(out)}
    jobs = [(c, v, ch) for c in clips() for v in VOICES for ch in CHANNELS
            if (c["clip"], v, ch, ASR_MODEL) not in done]
    print(f"{len(jobs)} recordings to transcribe")

    import threading

    lock = threading.Lock()

    def one(job):
        c, v, ch = job
        try:
            text = _scribe(_channel(AUDIO / v / f"{c['clip']}.mp3", ch), key)
        except Exception as e:  # HTTP, network, missing audio, ffmpeg: retried on the next run
            return f"{v}/{c['clip']}/{ch}: {type(e).__name__} {str(e)[:200]}"
        with lock:
            _append(out, [{"clip": c["clip"], "voice": v, "channel": ch, "asr": ASR_MODEL, "transcript": text}])
        return None

    with ThreadPoolExecutor(6) as pool:
        errors = [e for e in pool.map(one, jobs) if e]
    for e in errors[:10]:
        print("ASR error", e)
    if errors:
        sys.exit(1)


# --- extraction -----------------------------------------------------------------------

FORMATS = {
    "customer_code": "C- followed by 4 digits, e.g. C-1042",
    "delegation_ref": "DLG- followed by 4 capital letters or digits, e.g. DLG-7Q4K",
    "birth_date": "ISO date YYYY-MM-DD",
    "meter_reading": "5 digits, e.g. 45231",
    "amount": "euros with comma and 2 decimals, no symbol, e.g. 84,30",
    "pod": "IT + 3 digits + E + 8 digits, e.g. IT001E12345678",
    "iban": "Italian IBAN, 27 characters, no spaces, capital letters",
    "fiscal_code": "Italian codice fiscale, 16 characters, capital letters",
}


def _after_frame(transcript: str) -> str:
    """The rules extractor only reads what follows the caller's frame ('... è')."""
    m = re.search(r"\b(è|e')\s", transcript)
    return transcript[m.end():] if m else transcript


def _words(text: str) -> list[str]:
    """Lower-case words and digit runs, with number words the recogniser split rejoined."""
    toks = re.findall(r"[a-z]+|\d+|[,;.]", _strip_accents(text.lower()))
    return [w for w in _merge_split_numbers(toks) if w not in ",;."]


def rules_extract(etype: str, transcript: str) -> str | None:
    """A deterministic normaliser: number words to digits, spelled letters to letters, then the format."""
    tail = _after_frame(transcript)
    if etype == "birth_date":
        words = _words(tail)
        nums = [int(w) if w.isdigit() else parse_number_word(w) for w in words]
        month = next((MONTHS.index(w) + 1 for w in words if w in MONTHS), None)
        if "primo" in words:
            nums.insert(0, 1)
        nums = [n for n in nums if n is not None]
        if month and len(nums) >= 2:
            day, year = nums[0], nums[-1]
        elif len(nums) >= 3:
            day, month, year = nums[0], nums[1], nums[-1]
        else:
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    if etype == "amount":
        t = _strip_accents(tail.lower())
        m = re.search(r"(\d+)[,.](\d{2})", t)
        if m:
            return f"{int(m.group(1))},{m.group(2)}"
        words = _words(tail)
        nums = [int(w) if w.isdigit() else parse_number_word(w) for w in words]
        nums = [n for n in nums if n is not None]
        if "virgola" in words:  # digit by digit: 3, 1, 8, virgola, 0, 7
            i = words.index("virgola")
            left = "".join(str(int(w) if w.isdigit() else parse_number_word(w)) for w in words[:i]
                           if w.isdigit() or parse_number_word(w) is not None)
            right = "".join(str(int(w) if w.isdigit() else parse_number_word(w)) for w in words[i + 1:]
                            if w.isdigit() or parse_number_word(w) is not None)
            return f"{int(left)},{right[:2]:0<2}" if left else None
        if len(nums) >= 2:
            return f"{nums[0]},{nums[1]:02d}"
        return f"{nums[0]},00" if nums else None
    s = to_symbols(tail)
    patterns = {
        "customer_code": (r"C(\d{4})", "C-{}"),
        "delegation_ref": (r"DLG([A-Z0-9]{4})", "DLG-{}"),
        "meter_reading": (r"(\d{5})", "{}"),
        "pod": (r"(IT\d{3}E\d{8})", "{}"),
        "iban": (r"(IT\d{2}[A-Z]\d{10}[A-Z0-9]{12})", "{}"),
        "fiscal_code": (r"([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])", "{}"),
    }
    pat, fmt = patterns[etype]
    m = re.search(pat, s)
    return fmt.format(m.group(1)) if m else None


def _claude(model: str, etype: str, transcript: str, client) -> dict[str, Any]:
    from pydantic import BaseModel

    class Extraction(BaseModel):
        value: str | None
        unsure: bool

    prompt = (f"A caller to an Italian utility said this, as written by a speech recogniser:\n\n"
              f"<transcript>{transcript}</transcript>\n\n"
              f"Extract the {etype.replace('_', ' ')} ({FRAMES[etype]!r} introduces it). "
              f"Return it normalised as: {FORMATS[etype]}. Number words and spelled letters "
              f"('D come Domodossola') count. If it is missing or you would have to guess, set value to null. "
              f"Set unsure to true if you would ask the caller to repeat it.")
    r = client.messages.parse(model=model, max_tokens=4096, output_config={"effort": "low"},
                              messages=[{"role": "user", "content": prompt}], output_format=Extraction)
    p = r.parsed_output
    return {"value": p.value if p else None, "unsure": bool(p and p.unsure), "stop": r.stop_reason}


def run_extract(models: list[str]) -> None:
    """Claude extractions, cached in data/extractions.jsonl (the rules extractor is free and runs at
    scoring time). Each result is appended as it arrives; a failed call is retried on the next run."""
    import threading

    import anthropic

    out = DATA / "extractions.jsonl"
    done = {(r["clip"], r["voice"], r["channel"], r["extractor"]) for r in _jsonl(out)}
    meta = {c["clip"]: c for c in clips()}
    transcripts = _jsonl(DATA / "transcripts.jsonl")
    client = anthropic.Anthropic(api_key=_key("ANTHROPIC_API_KEY", "anthropic"), max_retries=4)
    lock = threading.Lock()
    for model in models:
        jobs = [t for t in transcripts if (t["clip"], t["voice"], t["channel"], model) not in done]

        def one(t, model=model):
            try:
                r = _claude(model, meta[t["clip"]]["type"], t["transcript"], client)
            except Exception as e:  # API error or a reply that does not parse: retried next run
                return f"{model} {t['clip']} {t['voice']} {t['channel']}: {type(e).__name__} {str(e)[:120]}"
            with lock:
                _append(out, [{**{k: t[k] for k in ("clip", "voice", "channel")}, "extractor": model, **r}])
            return None

        with ThreadPoolExecutor(8) as pool:
            errors = [e for e in pool.map(one, jobs) if e]
        print(f"{model}: {len(jobs) - len(errors)} new, {len(errors)} failed", *errors[:5], sep="\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("stage", choices=["tts", "asr", "extract"])
    p.add_argument("--models", nargs="*", default=CLAUDE_MODELS)
    a = p.parse_args()
    if a.stage == "tts":
        run_tts()
    elif a.stage == "asr":
        run_asr()
    else:
        run_extract(a.models)


if __name__ == "__main__":
    main()
