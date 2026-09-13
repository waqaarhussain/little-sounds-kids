#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig


LETTERS = [
    ("A", ["apple", "ant", "alligator", "axe"]),
    ("B", ["ball", "bear", "banana", "butterfly"]),
    ("C", ["cat", "car", "cup", "crab"]),
    ("D", ["dog", "duck", "drum", "dinosaur"]),
    ("E", ["egg", "elephant", "elbow", "envelope"]),
    ("F", ["fish", "frog", "fox", "flower"]),
    ("G", ["goat", "grapes", "gift", "goose"]),
    ("H", ["hat", "hen", "hippo", "house"]),
    ("I", ["ice", "insect", "ink", "iguana"]),
    ("J", ["jam", "jet", "jar", "jellyfish"]),
    ("K", ["kite", "king", "kitten", "koala"]),
    ("L", ["lion", "leaf", "lamp", "lemon"]),
    ("M", ["moon", "mouse", "milk", "monkey"]),
    ("N", ["nest", "net", "nose", "nut"]),
    ("O", ["octopus", "orange", "ox", "ostrich"]),
    ("P", ["pig", "pen", "pizza", "panda"]),
    ("Q", ["queen", "quill", "quilt", "question"]),
    ("R", ["rabbit", "rain", "robot", "rocket"]),
    ("S", ["sun", "sock", "snake", "star"]),
    ("T", ["tiger", "tree", "train", "turtle"]),
    ("U", ["umbrella", "up", "uncle", "under"]),
    ("V", ["van", "vase", "violin", "volcano"]),
    ("W", ["whale", "web", "watch", "watermelon"]),
    ("X", ["box", "fox", "six", "axe"]),
    ("Y", ["yak", "yarn", "yellow", "yo-yo"]),
    ("Z", ["zebra", "zip", "zero", "zoo"]),
]

TRACING_PHRASES = {
    **{str(number): str(number) for number in range(1, 10)},
    "circle": "circle",
    "square": "square",
    "triangle": "triangle",
    "diamond": "diamond",
    "pentagon": "pentagon",
    "heart": "heart",
    "star": "star",
    "hexagon": "hexagon",
    "oval": "oval",
}


def slug(value: str) -> str:
    return value.lower().replace(" ", "-")


def run_ffmpeg(*arguments: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=True,
    )


def encode_mp3(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg("-i", str(source), "-codec:a", "libmp3lame", "-q:a", "4", str(destination))


def convert_phonics(source: Path, wav_destination: Path, mp3_destination: Path) -> None:
    wav_destination.parent.mkdir(parents=True, exist_ok=True)
    mp3_destination.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        "-i",
        str(source),
        "-ar",
        "22050",
        "-ac",
        "1",
        "-sample_fmt",
        "s16",
        str(wav_destination),
    )
    encode_mp3(wav_destination, mp3_destination)


def synthesise(voice: PiperVoice, text: str, destination: Path, length_scale: float = 1.08) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    config = SynthesisConfig(length_scale=length_scale, normalize_audio=True, volume=0.94)
    with wave.open(str(destination), "wb") as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=config)


def append_wav(output: wave.Wave_write, source: Path) -> None:
    with wave.open(str(source), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 22050):
            raise RuntimeError(f"Unexpected WAV format: {source}")
        output.writeframes(audio.readframes(audio.getnframes()))


def append_silence(output: wave.Wave_write, milliseconds: int) -> None:
    frame_count = int(22050 * milliseconds / 1000)
    output.writeframes(b"\x00\x00" * frame_count)


def make_page_audio(letter_wav: Path, word_wavs: list[Path], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        append_wav(output, letter_wav)
        append_silence(output, 720)
        for index, word_wav in enumerate(word_wavs):
            append_wav(output, word_wav)
            if index < len(word_wavs) - 1:
                append_silence(output, 680)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--phonics-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    voice = PiperVoice.load(str(args.model))
    unique_words = sorted({word for _, words in LETTERS for word in words})

    with tempfile.TemporaryDirectory(prefix="phonics-audio-") as temporary_directory:
        temporary = Path(temporary_directory)
        word_wavs: dict[str, Path] = {}

        for word in unique_words:
            word_slug = slug(word)
            word_wav = temporary / "words" / f"{word_slug}.wav"
            synthesise(voice, word, word_wav, 1.12)
            encode_mp3(word_wav, output / "words" / f"{word_slug}.mp3")
            word_wavs[word] = word_wav

            find_wav = temporary / "find" / f"{word_slug}.wav"
            synthesise(voice, f"Can you find the {word}?", find_wav, 1.08)
            encode_mp3(find_wav, output / "find" / f"{word_slug}.mp3")

        for letter, words in LETTERS:
            letter_key = letter.lower()
            phonics_source = args.phonics_dir / f"{letter_key}.ogg"
            if not phonics_source.is_file():
                raise FileNotFoundError(phonics_source)

            phonics_wav = temporary / "phonics" / f"{letter_key}.wav"
            convert_phonics(
                phonics_source,
                phonics_wav,
                output / "phonics" / f"{letter_key}.mp3",
            )

            page_wav = temporary / "pages" / f"{letter_key}.wav"
            make_page_audio(phonics_wav, [word_wavs[word] for word in words], page_wav)
            encode_mp3(page_wav, output / "pages" / f"{letter_key}.mp3")

            for word in words:
                word_slug = slug(word)
                success_wav = temporary / "success" / f"{letter_key}-{word_slug}.wav"
                synthesise(
                    voice,
                    f"Yes! {word}. {word} starts with {letter}. Well done!",
                    success_wav,
                    1.08,
                )
                encode_mp3(success_wav, output / "success" / f"{letter_key}-{word_slug}.mp3")

        ui_phrases = {
            "sound-on": "Sound on.",
            "try-another-one": "Try another one.",
            "well-done": "Well done!",
        }
        for filename, phrase in ui_phrases.items():
            ui_wav = temporary / "ui" / f"{filename}.wav"
            synthesise(voice, phrase, ui_wav, 1.08)
            encode_mp3(ui_wav, output / "ui" / f"{filename}.mp3")

        for filename, phrase in TRACING_PHRASES.items():
            tracing_wav = temporary / "tracing" / f"{filename}.wav"
            synthesise(voice, phrase, tracing_wav, 1.08)
            encode_mp3(tracing_wav, output / "tracing" / f"{filename}.mp3")

    audio_files = list(output.rglob("*.mp3"))
    expected = len(unique_words) * 2 + len(LETTERS) * 6 + len(ui_phrases) + len(TRACING_PHRASES)
    if len(audio_files) != expected:
        raise RuntimeError(f"Expected {expected} audio files, generated {len(audio_files)}")
    print(f"Generated {len(audio_files)} consistent audio files.")


if __name__ == "__main__":
    main()
