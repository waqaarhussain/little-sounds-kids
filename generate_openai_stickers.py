#!/usr/bin/env python3

import argparse
import base64
import hashlib
import html
import io
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import imagehash
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from PIL import Image, ImageDraw, ImageFilter


MODEL = "gpt-image-2.5-sunburst"

CATEGORIES = {
    "super-kitties": {
        "label": "SuperKitties",
        "ideas": [
            "Ginny leaping forward in a brave rescue pose with sparkling stars",
            "Sparks proudly holding a clever glowing gadget with electric doodles",
            "Buddy lifting a playful cartoon boulder in a strong superhero pose",
            "Bitsy zooming forward with an excited smile and colourful speed trails",
            "Ginny and Bitsy sharing a joyful mid-air high five",
            "Sparks and Buddy standing back-to-back in a confident hero pose",
            "Ginny, Sparks, Buddy and Bitsy together in a cheerful team huddle",
            "the four SuperKitties soaring together with capes and starbursts",
            "the SuperKitties dancing together with musical notes and confetti",
            "the full SuperKitties team celebrating a successful rescue with paws raised",
        ],
    },
    "paw-patrol": {
        "label": "Paw Patrol",
        "ideas": [
            "Chase jumping forward happily in his blue police uniform with gold stars",
            "Marshall sitting playfully in his red firefighter uniform with one paw raised",
            "Skye flying joyfully in her pink aviator uniform with pink starbursts",
            "Rubble charging forward cheerfully in his yellow construction uniform",
            "Rocky posing proudly with a small recycling tool and green confetti",
            "Zuma splashing through a curl of bright blue water in his orange uniform",
            "Everest sliding through sparkling snow in her teal snow-rescue uniform",
            "Liberty doing an energetic superhero landing with coral-and-blue accents",
            "Chase and Marshall sharing a playful high five surrounded by stars",
            "the core Paw Patrol pups together in a compact joyful team celebration",
        ],
    },
    "bluey": {
        "label": "Bluey",
        "ideas": [
            "Bluey doing a silly happy dance with colourful music-note doodles",
            "Bingo jumping excitedly while holding a small rainbow ball",
            "Bluey and Bingo hugging and laughing with hearts and stars",
            "Bandit playing aeroplane with Bluey in a playful compact composition",
            "Chilli waving warmly with cheerful flower and heart doodles",
            "Bluey, Bingo, Bandit and Chilli together in a joyful family cuddle",
            "Muffin racing forward with an amusing determined expression and speed lines",
            "Socks bouncing playfully with small paw-print doodles",
            "Rusty swinging a cricket bat in a fun action pose with stars",
            "Bluey and several friends celebrating together with confetti",
        ],
    },
    "pj-masks": {
        "label": "PJ Masks",
        "ideas": [
            "Catboy springing forward in a fast superhero pose with blue speed trails",
            "Owlette soaring upward with her red wings open and sparkling stars",
            "Gekko standing proudly in a powerful pose with green energy doodles",
            "Catboy, Owlette and Gekko together in a compact triumphant team pose",
            "Catboy crouching on a crescent moon shape, ready to leap",
            "Owlette making a graceful mid-air spin surrounded by red feathers and stars",
            "Gekko lifting a playful cartoon rock above his head with a big smile",
            "Catboy and Gekko racing side by side with blue and green action lines",
            "Owlette leading Catboy and Gekko in a flying action composition",
            "the three PJ Masks heroes celebrating together with fists raised and confetti",
        ],
    },
    "minnie-mouse": {
        "label": "Minnie Mouse",
        "ideas": [
            "Minnie Mouse waving in her classic polka-dot bow and dress with hearts",
            "Minnie Mouse twirling happily in a sparkling pink party dress",
            "Minnie Mouse dressed as a cheerful baker holding a decorated cupcake",
            "Minnie Mouse dressed as an artist holding a paintbrush and colourful palette",
            "Minnie Mouse gardening with a bright flower and butterfly doodles",
            "Minnie Mouse in a playful space explorer outfit floating among stars",
            "Minnie Mouse celebrating a birthday with a tiny gift and confetti",
            "Minnie Mouse and Daisy Duck sharing a joyful high five",
            "Minnie Mouse and Mickey Mouse dancing together in a compact happy pose",
            "Minnie Mouse celebrating with Daisy, Mickey, Donald and Goofy as a close group",
        ],
    },
    "mickey-mouse": {
        "label": "Mickey Mouse",
        "ideas": [
            "Mickey Mouse waving in his classic red shorts and yellow shoes with stars",
            "Mickey Mouse dressed as a magician making colourful sparkles appear",
            "Mickey Mouse in a playful astronaut suit floating beside a small moon",
            "Mickey Mouse dressed as an explorer holding a tiny treasure map",
            "Mickey Mouse happily playing a bright red guitar with music-note doodles",
            "Mickey Mouse celebrating a birthday with a party hat and confetti",
            "Mickey Mouse kicking a football in an energetic action pose",
            "Mickey Mouse and Pluto cuddling in a joyful compact composition",
            "Mickey Mouse, Donald Duck and Goofy sharing a funny team pose",
            "Mickey Mouse celebrating with Minnie, Donald, Daisy, Goofy and Pluto as a close group",
        ],
    },
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_prompt(label, idea, number, retry_number):
    retry_instruction = ""
    if retry_number:
        retry_instruction = (
            f" This is alternate attempt {retry_number + 1}; make the silhouette, pose, camera angle, "
            "facial expression and decorative doodles substantially different from earlier designs."
        )
    return (
        f"Create exactly one premium die-cut children's reward sticker featuring {idea}, "
        f"faithfully recognisable as the {label} characters. High-end polished 3D CGI cartoon rendering, "
        "soft detailed fur or fabric, expressive friendly face, joyful preschool energy, vivid clean colours, "
        "studio-quality lighting, full character visible, centred compact composition. Add a thick smooth white "
        "vinyl cut-line and a few colourful stars, hearts, action lines or confetti immediately around the subject. "
        "Transparent background outside the sticker cut-line. Exactly one sticker design in the image, even when "
        "the design contains a character group. No sticker sheet, no separate panels, no scenery, no black background, "
        "no checkerboard, no words, no letters, no numbers, no logo, no watermark, no interface elements, no cropped "
        f"heads or limbs.{retry_instruction}"
    )


def normalise_sticker(raw_bytes):
    image = Image.open(io.BytesIO(raw_bytes))
    image.seek(0)
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] > 245:
        image = image.copy()
        for corner in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)):
            ImageDraw.floodfill(image, corner, (0, 0, 0, 0), thresh=34)
    bounds = image.getbbox()
    if not bounds:
        raise ValueError("The generated image was empty.")
    subject = image.crop(bounds)
    subject.thumbnail((570, 570), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
    x = (640 - subject.width) // 2
    y = (640 - subject.height) // 2
    subject_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    subject_layer.alpha_composite(subject, (x, y))
    mask = subject_layer.getchannel("A")
    outline = mask.filter(ImageFilter.MaxFilter(17))
    shadow = outline.filter(ImageFilter.GaussianBlur(9))
    shadow_layer = Image.new("RGBA", canvas.size, (29, 38, 66, 0))
    shadow_layer.putalpha(shadow.point(lambda value: round(value * 0.23)))
    canvas.alpha_composite(shadow_layer, (0, 7))
    white = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    white.putalpha(outline)
    canvas.alpha_composite(white)
    canvas.alpha_composite(subject_layer)
    return canvas


def visual_hash(image):
    flattened = Image.new("RGB", image.size, "white")
    flattened.paste(image, mask=image.getchannel("A"))
    return imagehash.phash(flattened.resize((256, 256), Image.Resampling.LANCZOS))


def load_manifest(path):
    if not path.is_file():
        return {"model": MODEL, "quality": None, "created_at": utc_now(), "items": [], "failures": []}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"model": MODEL, "quality": None, "created_at": utc_now(), "items": [], "failures": []}


def write_manifest(path, manifest):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(path)


def write_gallery(public_root, manifest, planned_total):
    items = manifest.get("items", [])
    by_category = {category: [] for category in CATEGORIES}
    for item in items:
        if item.get("category") in by_category and int(item.get("number", 0)) <= planned_total:
            by_category[item["category"]].append(item)
    sections = []
    for category, details in CATEGORIES.items():
        cards = []
        for item in sorted(by_category[category], key=lambda value: value["number"]):
            image_path = f"{category}/{item['number']:03d}.webp"
            cards.append(
                f'<article><span>#{item["number"]}</span><img src="{html.escape(image_path)}" '
                f'alt="{html.escape(details["label"])} sticker {item["number"]}" loading="lazy"></article>'
            )
        missing = max(0, planned_total - len(cards))
        placeholders = "".join('<article class="waiting">Generating…</article>' for _ in range(missing))
        sections.append(
            f'<section><h2>{html.escape(details["label"])} <small>{len(cards)}/{planned_total}</small></h2>'
            f'<div class="grid">{"".join(cards)}{placeholders}</div></section>'
        )
    generated = sum(
        1 for item in items
        if item.get("category") in CATEGORIES and int(item.get("number", 0)) <= planned_total
    )
    total = planned_total * len(CATEGORIES)
    page = f'''<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><meta http-equiv="refresh" content="30"><title>AI Sticker Trial</title>
<style>*{{box-sizing:border-box}}body{{margin:0;padding:24px clamp(14px,4vw,44px);font-family:ui-rounded,"Arial Rounded MT Bold",system-ui,sans-serif;color:#243557;background:linear-gradient(155deg,#64cdf5,#f4e9ff 50%,#fff0a6)}}header{{max-width:1100px;margin:auto;text-align:center}}h1{{font-size:clamp(2rem,7vw,4.4rem);margin:0;text-shadow:0 4px #fff}}header p{{font-weight:900}}main{{max-width:1100px;margin:auto}}section{{margin:30px 0;padding:18px;border:5px solid #fff;border-radius:28px;background:#ffffffb8;box-shadow:0 9px 24px #40547b24}}h2{{margin:0 0 14px;font-size:clamp(1.5rem,4vw,2.2rem)}}small{{color:#7258e8}}.grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px}}article{{position:relative;aspect-ratio:1;border-radius:20px;background:#fff;box-shadow:0 6px 14px #35476a20;display:grid;place-items:center;overflow:hidden}}article span{{position:absolute;z-index:2;top:7px;left:7px;padding:5px 8px;border-radius:99px;background:#ffe15c;font-weight:1000}}img{{width:100%;height:100%;object-fit:contain}}.waiting{{color:#75829b;font-weight:900;border:3px dashed #b9c4d6;background:#f8fbff}}a{{color:inherit}}@media(max-width:760px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}section{{padding:12px}}}}</style></head>
<body><header><h1>✨ AI Sticker Trial</h1><p>{generated}/{total} generated. This page refreshes every 30 seconds.</p><p><a href="/">◀ Back to Little Learners</a></p></header><main>{''.join(sections)}</main></body></html>'''
    public_root.mkdir(parents=True, exist_ok=True)
    temporary = public_root / "index.tmp"
    temporary.write_text(page)
    temporary.replace(public_root / "index.html")


def generate_image(client, prompt):
    response = client.images.generate(
        model=MODEL,
        prompt=prompt,
        size="1024x1024",
        quality="medium",
        background="transparent",
        output_format="png",
    )
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("OpenAI returned no image data.")
    return base64.b64decode(response.data[0].b64_json), getattr(response, "usage", None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--private-root", type=Path, default=Path("/root/stickers/openai"))
    parser.add_argument("--public-root", type=Path, default=Path("/var/www/little-sounds/ai-stickers"))
    args = parser.parse_args()
    if not 1 <= args.count <= 200:
        raise ValueError("Count must be between 1 and 200.")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    args.private_root.mkdir(parents=True, exist_ok=True)
    args.public_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.private_root / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["model"] = MODEL
    manifest["quality"] = "medium"
    manifest["requested_per_category"] = args.count
    client = OpenAI(api_key=api_key, timeout=180.0, max_retries=0)
    try:
        client.models.list()
    except Exception as error:
        raise RuntimeError(f"The API key could not be verified: {error}") from error

    existing_keys = {(item["category"], int(item["number"])) for item in manifest.get("items", [])}
    hashes = {category: [] for category in CATEGORIES}
    for item in manifest.get("items", []):
        category = item.get("category")
        fingerprint = item.get("phash")
        if category in hashes and fingerprint:
            hashes[category].append(imagehash.hex_to_hash(fingerprint))

    write_gallery(args.public_root, manifest, args.count)
    total = args.count * len(CATEGORIES)
    completed = sum(1 for category, number in existing_keys if category in CATEGORIES and number <= args.count)
    print(f"Starting the {total}-sticker trial with {MODEL} at medium quality.", flush=True)
    print(f"Existing completed files: {completed}/{total}", flush=True)

    for category, details in CATEGORIES.items():
        private_category = args.private_root / category
        public_category = args.public_root / category
        private_category.mkdir(parents=True, exist_ok=True)
        public_category.mkdir(parents=True, exist_ok=True)
        ideas = details["ideas"]
        for number in range(1, args.count + 1):
            key = (category, number)
            private_file = private_category / f"{number:03d}.png"
            public_file = public_category / f"{number:03d}.webp"
            if key in existing_keys and private_file.is_file() and public_file.is_file():
                print(f"[{completed}/{total}] {details['label']} #{number}: already complete", flush=True)
                continue
            idea = ideas[(number - 1) % len(ideas)]
            saved = False
            last_error = None
            for design_attempt in range(4):
                prompt = make_prompt(details["label"], idea, number, design_attempt)
                raw = None
                usage = None
                for api_attempt in range(6):
                    try:
                        raw, usage = generate_image(client, prompt)
                        break
                    except (RateLimitError, APITimeoutError, APIConnectionError) as error:
                        last_error = error
                        delay = min(90, 12 * (api_attempt + 1)) + random.uniform(0, 3)
                        print(f"Rate/network wait for {details['label']} #{number}: {delay:.0f}s", flush=True)
                        time.sleep(delay)
                    except APIStatusError as error:
                        last_error = error
                        if error.status_code == 429 or error.status_code >= 500:
                            delay = min(90, 12 * (api_attempt + 1)) + random.uniform(0, 3)
                            print(f"API wait for {details['label']} #{number}: {delay:.0f}s", flush=True)
                            time.sleep(delay)
                        else:
                            break
                    except Exception as error:
                        last_error = error
                        break
                else:
                    continue
                if raw is None:
                    continue
                try:
                    sticker = normalise_sticker(raw)
                    fingerprint = visual_hash(sticker)
                    if any(fingerprint - previous <= 8 for previous in hashes[category]):
                        last_error = RuntimeError("The result was visually too similar to an existing sticker.")
                        raw = None
                        continue
                    sticker.save(private_file, "PNG", optimize=True)
                    sticker.save(public_file, "WEBP", quality=90, method=6)
                    sha256 = hashlib.sha256(private_file.read_bytes()).hexdigest()
                    manifest["items"] = [
                        item for item in manifest.get("items", [])
                        if not (item.get("category") == category and int(item.get("number", 0)) == number)
                    ]
                    manifest["items"].append(
                        {
                            "category": category,
                            "category_label": details["label"],
                            "number": number,
                            "idea": idea,
                            "prompt": prompt,
                            "model": MODEL,
                            "quality": "medium",
                            "sha256": sha256,
                            "phash": str(fingerprint),
                            "generated_at": utc_now(),
                            "usage": usage.model_dump() if hasattr(usage, "model_dump") else None,
                        }
                    )
                    manifest["failures"] = [
                        item for item in manifest.get("failures", [])
                        if not (item.get("category") == category and int(item.get("number", 0)) == number)
                    ]
                    hashes[category].append(fingerprint)
                    existing_keys.add(key)
                    completed += 1
                    write_manifest(manifest_path, manifest)
                    write_gallery(args.public_root, manifest, args.count)
                    print(f"[{completed}/{total}] {details['label']} #{number}: saved", flush=True)
                    saved = True
                    raw = None
                    break
                except Exception as error:
                    last_error = error
                    raw = None
            if not saved:
                message = str(last_error) if last_error else "Unknown generation failure"
                manifest.setdefault("failures", []).append(
                    {"category": category, "number": number, "error": message, "failed_at": utc_now()}
                )
                write_manifest(manifest_path, manifest)
                write_gallery(args.public_root, manifest, args.count)
                print(f"FAILED {details['label']} #{number}: {message}", file=sys.stderr, flush=True)

    generated = sum(
        1 for item in manifest.get("items", [])
        if item.get("category") in CATEGORIES and int(item.get("number", 0)) <= args.count
    )
    write_gallery(args.public_root, manifest, args.count)
    print(f"Generation finished: {generated}/{total} trial stickers available.", flush=True)
    print("Preview: /ai-stickers/", flush=True)
    if generated != total:
        sys.exit(2)


if __name__ == "__main__":
    main()
