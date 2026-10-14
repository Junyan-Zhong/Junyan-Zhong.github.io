#!/usr/bin/env python3
import html as html_lib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SOURCE = Path("law-school-days.html")
OUTPUT = Path("law-school-days.mp3")
CHUNKS_DIR = Path(".audio_chunks")

VOICE = "marin"
MODEL = "gpt-4o-mini-tts"
INSTRUCTIONS = (
    "Read this as a literary personal essay collection. Use a warm, calm, intelligent, "
    "reflective voice. Keep the pace natural and slightly unhurried. Respect paragraph "
    "breaks with gentle pauses. Avoid sounding promotional, theatrical, sentimental, or "
    "overly dramatic. Let humor remain light. Pronounce names and book titles carefully."
)

def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_lib.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()

def extract_narration(doc: str) -> list[str]:
    cards = re.findall(r'<article class="note-card">(.*?)</article>', doc, flags=re.S)
    paragraphs = []
    for card in cards:
        # Exclude expandable Original 中文.
        card = re.sub(r"<details>.*?</details>", "", card, flags=re.S)

        m = re.search(r'<time[^>]*datetime="(\d{4})-(\d{2})-(\d{2})"[^>]*>.*?</time>', card, flags=re.S)
        if m:
            y, mo, d = m.groups()
            paragraphs.append(f"{mo}/{d}/{y}")

        # Include top-level paragraphs and paragraphs inside blockquotes.
        for p in re.findall(r"<p(?:\s[^>]*)?>(.*?)</p>", card, flags=re.S):
            text = strip_tags(p)
            if text:
                paragraphs.append(text)
    return paragraphs

def chunk_text(paragraphs: list[str], limit: int = 3800) -> list[str]:
    chunks = []
    current = ""
    for p in paragraphs:
        candidate = p if not current else current + "\n\n" + p
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(p) <= limit:
                current = p
            else:
                # Sentence-aware fallback for an unusually long paragraph.
                parts = re.split(r"(?<=[.!?])\s+", p)
                current = ""
                for part in parts:
                    candidate = part if not current else current + " " + part
                    if len(candidate) <= limit:
                        current = candidate
                    else:
                        if current:
                            chunks.append(current)
                        current = part
    if current:
        chunks.append(current)
    return chunks

def create_speech(text: str, out_path: Path, api_key: str) -> None:
    payload = json.dumps({
        "model": MODEL,
        "voice": VOICE,
        "input": text,
        "instructions": INSTRUCTIONS,
        "response_format": "mp3"
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            out_path.write_bytes(resp.read())
    except Exception as exc:
        print(f"OpenAI speech request failed: {exc}", file=sys.stderr)
        raise

def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set.")

    doc = SOURCE.read_text(encoding="utf-8")
    paragraphs = extract_narration(doc)
    chunks = chunk_text(paragraphs)

    if not chunks:
        raise SystemExit("No narration text found.")

    CHUNKS_DIR.mkdir(exist_ok=True)
    mp3_files = []

    for i, chunk in enumerate(chunks, start=1):
        out = CHUNKS_DIR / f"chunk-{i:03d}.mp3"
        print(f"Generating {i}/{len(chunks)} ({len(chunk)} chars)")
        create_speech(chunk, out, api_key)
        mp3_files.append(out)

    concat_file = CHUNKS_DIR / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in mp3_files) + "\n",
        encoding="utf-8"
    )

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", str(OUTPUT)
    ], check=True)

    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")

if __name__ == "__main__":
    main()
