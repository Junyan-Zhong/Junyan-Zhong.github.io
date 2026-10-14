#!/usr/bin/env python3
import html as html_lib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

VOICE = "marin"
MODEL = "gpt-4o-mini-tts"
INSTRUCTIONS = (
    "Read this as a literary personal essay. Use a warm, calm, intelligent, reflective voice. "
    "Keep the pace natural and slightly unhurried. Respect paragraph breaks with gentle pauses. "
    "Avoid sounding promotional, theatrical, sentimental, or overly dramatic. Let humor remain light. "
    "Pronounce names, book titles, film titles, and musical-theater titles carefully."
)

ESSAYS = [
    ("sunday-in-the-park-with-george.html", "sunday-in-the-park-with-george.mp3"),
    ("the-last-five-years.html", "the-last-five-years.mp3"),
    ("sentimental-value.html", "sentimental-value.mp3"),
]

def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_lib.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()

def extract_narration(doc: str) -> list[str]:
    main_match = re.search(r"<main[^>]*>(.*?)</main>", doc, flags=re.S | re.I)
    if not main_match:
        return []
    main = main_match.group(1)

    # Exclude notes that are metadata rather than part of the essay.
    main = re.sub(r'<p class="source-note">.*?</p>', "", main, flags=re.S | re.I)

    parts = []

    title = re.search(r"<h1[^>]*>(.*?)</h1>", main, flags=re.S | re.I)
    if title:
        parts.append(strip_tags(title.group(1)))

    lede = re.search(r'<p class="lede"[^>]*>(.*?)</p>', main, flags=re.S | re.I)
    if lede:
        parts.append(strip_tags(lede.group(1)))

    # Narrate essay paragraphs and blockquotes in document order.
    body_start = 0
    if lede:
        body_start = lede.end()
    body = main[body_start:]

    for m in re.finditer(r"<p(?:\s[^>]*)?>(.*?)</p>", body, flags=re.S | re.I):
        text = strip_tags(m.group(1))
        if text:
            parts.append(text)

    return parts

def chunk_text(paragraphs: list[str], limit: int = 3800) -> list[str]:
    chunks = []
    current = ""
    for p in paragraphs:
        candidate = p if not current else current + "\n\n" + p
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(p) <= limit:
            current = p
            continue

        current = ""
        for sentence in re.split(r"(?<=[.!?])\s+", p):
            candidate = sentence if not current else current + " " + sentence
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = sentence

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

    with urllib.request.urlopen(req, timeout=180) as resp:
        out_path.write_bytes(resp.read())

def generate_one(source_name: str, output_name: str, api_key: str) -> None:
    source = Path(source_name)
    output = Path(output_name)
    chunks_dir = Path(".audio_chunks") / source.stem
    chunks_dir.mkdir(parents=True, exist_ok=True)

    doc = source.read_text(encoding="utf-8")
    paragraphs = extract_narration(doc)
    chunks = chunk_text(paragraphs)
    if not chunks:
        raise RuntimeError(f"No narration text found in {source_name}")

    files = []
    for i, chunk in enumerate(chunks, start=1):
        out = chunks_dir / f"chunk-{i:03d}.mp3"
        print(f"{source_name}: generating {i}/{len(chunks)} ({len(chunk)} chars)")
        create_speech(chunk, out, api_key)
        files.append(out)

    concat_file = chunks_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in files) + "\n",
        encoding="utf-8"
    )

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", str(output)
    ], check=True)

    print(f"Wrote {output} ({output.stat().st_size} bytes)")

def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set.")

    for source_name, output_name in ESSAYS:
        try:
            generate_one(source_name, output_name, api_key)
        except Exception as exc:
            print(f"Failed on {source_name}: {exc}", file=sys.stderr)
            raise

if __name__ == "__main__":
    main()
