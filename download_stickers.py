#!/usr/bin/env python3

import argparse
import hashlib
import io
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import imagehash
    from ddgs import DDGS
except ImportError:
    imagehash = None
    DDGS = None


CATEGORIES = {
    "paw-patrol": {
        "label": "Paw Patrol",
        "queries": [
            "Paw Patrol sticker transparent png",
            "Paw Patrol characters clipart transparent",
            "Chase Paw Patrol sticker png",
            "Marshall Paw Patrol sticker png",
            "Skye Paw Patrol sticker png",
            "Rubble Rocky Zuma Paw Patrol png",
            "Everest Liberty Tracker Paw Patrol png",
        ],
    },
    "pj-masks": {
        "label": "PJ Masks",
        "queries": [
            "PJ Masks sticker transparent png",
            "PJ Masks characters clipart transparent",
            "Catboy PJ Masks sticker png",
            "Owlette PJ Masks sticker png",
            "Gekko PJ Masks sticker png",
            "PJ Masks heroes group transparent png",
            "PJ Masks character poses png",
        ],
    },
    "mickey-mouse": {
        "label": "Mickey Mouse",
        "queries": [
            "Mickey Mouse sticker transparent png",
            "Mickey Mouse different poses png",
            "Mickey Mouse celebration clipart",
            "Mickey Mouse thumbs up transparent",
            "Mickey Mouse star sticker png",
            "Mickey Mouse happy transparent png",
            "Mickey Mouse clubhouse sticker png",
        ],
    },
    "minnie-mouse": {
        "label": "Minnie Mouse",
        "queries": [
            "Minnie Mouse sticker transparent png",
            "Minnie Mouse different poses png",
            "Minnie Mouse celebration clipart",
            "Minnie Mouse bow transparent png",
            "Minnie Mouse star sticker png",
            "Minnie Mouse happy transparent png",
            "Minnie Mouse clubhouse sticker png",
        ],
    },
    "bluey": {
        "label": "Bluey",
        "queries": [
            "Bluey sticker transparent png",
            "Bluey characters clipart transparent",
            "Bluey Bingo sticker png",
            "Bluey family transparent png",
            "Muffin Socks Bluey png",
            "Bandit Chilli Bluey png",
            "Bluey friends character png",
        ],
    },
}

SCHOOL_CATEGORIES = {
    "smiley-faces": "Smiley Faces",
    "well-done": "Well Done",
    "youre-a-star": "You're a Star",
}
OPENMOJI_VERSION = "15.1.0"
OPENMOJI_BASE = f"https://raw.githubusercontent.com/hfg-gmuend/openmoji/{OPENMOJI_VERSION}"


def image_bytes(session: requests.Session, url: str) -> bytes:
    response = session.get(url, timeout=(8, 22), stream=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "image" not in content_type and not url.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise ValueError("Not an image response")
    maximum = 12 * 1024 * 1024
    chunks = []
    size = 0
    for chunk in response.iter_content(65536):
        size += len(chunk)
        if size > maximum:
            raise ValueError("Image was larger than 12 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def connected_subject_boxes(alpha: Image.Image) -> list[tuple[int, int, int, int]]:
    scale = min(1.0, 220 / max(alpha.size))
    mask = alpha.resize(
        (max(1, round(alpha.width * scale)), max(1, round(alpha.height * scale))),
        Image.Resampling.BILINEAR,
    ).point(lambda value: 255 if value > 48 else 0)
    mask = mask.filter(ImageFilter.MaxFilter(7))
    width, height = mask.size
    pixels = mask.load()
    visited = bytearray(width * height)
    boxes = []
    minimum_area = width * height * 0.012
    for start_y in range(height):
        for start_x in range(width):
            index = start_y * width + start_x
            if visited[index] or pixels[start_x, start_y] == 0:
                continue
            stack = [(start_x, start_y)]
            visited[index] = 1
            min_x = max_x = start_x
            min_y = max_y = start_y
            area = 0
            while stack:
                x, y = stack.pop()
                area += 1
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
                for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= next_x < width and 0 <= next_y < height:
                        next_index = next_y * width + next_x
                        if not visited[next_index] and pixels[next_x, next_y] != 0:
                            visited[next_index] = 1
                            stack.append((next_x, next_y))
            box_width, box_height = max_x - min_x + 1, max_y - min_y + 1
            ratio = box_width / max(1, box_height)
            if area >= minimum_area and 0.3 <= ratio <= 3.3:
                boxes.append((min_x, min_y, max_x + 1, max_y + 1))
    return boxes


def prepare_subjects(raw: bytes) -> list[Image.Image]:
    image = Image.open(io.BytesIO(raw))
    image.seek(0)
    image = image.convert("RGBA")
    image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    if image.width < 180 or image.height < 180:
        raise ValueError("Image was too small")
    ratio = image.width / image.height
    if ratio < 0.42 or ratio > 2.35:
        raise ValueError("Image looked like a banner")

    original_alpha = image.getchannel("A")
    transparent_pixels = sum(original_alpha.histogram()[:245])
    transparent_ratio = transparent_pixels / (image.width * image.height)
    if transparent_ratio < 0.025:
        image = image.copy()
        for corner in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)):
            ImageDraw.floodfill(image, corner, (0, 0, 0, 0), thresh=38)

    alpha = image.getchannel("A").point(lambda value: 0 if value < 22 else value)
    image.putalpha(alpha)
    bounds = image.getbbox()
    if not bounds:
        raise ValueError("Image became empty")
    subject = image.crop(bounds)
    occupied = (subject.width * subject.height) / (image.width * image.height)
    subject_alpha = subject.getchannel("A")
    alpha_transparent = sum(subject_alpha.histogram()[:245]) / (subject.width * subject.height)
    if occupied > 0.96 and alpha_transparent < 0.02:
        raise ValueError("Image looked like a wallpaper")
    corners = (
        subject_alpha.getpixel((0, 0)),
        subject_alpha.getpixel((subject.width - 1, 0)),
        subject_alpha.getpixel((0, subject.height - 1)),
        subject_alpha.getpixel((subject.width - 1, subject.height - 1)),
    )
    subject_ratio = subject.width / subject.height
    if all(value > 245 for value in corners) and alpha_transparent < 0.02 and not 0.9 <= subject_ratio <= 1.1:
        raise ValueError("Image had an opaque rectangular background")

    boxes = connected_subject_boxes(subject.getchannel("A"))
    if len(boxes) < 4:
        return [subject]

    mask_width = min(220, subject.width)
    scale = mask_width / subject.width
    if round(subject.height * scale) > 220:
        scale = 220 / subject.height
    extracted = []
    for left, top, right, bottom in boxes:
        padding = 5
        crop_box = (
            max(0, int(left / scale) - padding),
            max(0, int(top / scale) - padding),
            min(subject.width, int(right / scale) + padding),
            min(subject.height, int(bottom / scale) + padding),
        )
        candidate = subject.crop(crop_box)
        if candidate.width >= 70 and candidate.height >= 70:
            extracted.append(candidate)
    return extracted or [subject]


def make_sticker(subject: Image.Image) -> Image.Image:
    subject = subject.copy()
    subject.thumbnail((530, 530), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
    x = (640 - subject.width) // 2
    y = (640 - subject.height) // 2
    subject_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    subject_layer.alpha_composite(subject, (x, y))
    mask = subject_layer.getchannel("A")
    outline = mask.filter(ImageFilter.MaxFilter(31))
    shadow = outline.filter(ImageFilter.GaussianBlur(12))
    shadow_layer = Image.new("RGBA", canvas.size, (35, 43, 72, 0))
    shadow_layer.putalpha(shadow.point(lambda value: int(value * 0.28)))
    canvas.alpha_composite(shadow_layer, (0, 9))
    white = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    white.putalpha(outline)
    canvas.alpha_composite(white)
    canvas.alpha_composite(subject_layer)
    return canvas


def visual_hash(sticker: Image.Image):
    if imagehash is None:
        raise RuntimeError("Install ImageHash before using online sticker search")
    flattened = Image.new("RGB", sticker.size, "white")
    flattened.paste(sticker, mask=sticker.getchannel("A"))
    return imagehash.phash(flattened.resize((256, 256)))


def school_sticker(icon: Image.Image, category: str, index: int) -> Image.Image:
    palettes = [
        (255, 101, 133), (75, 123, 236), (22, 177, 142), (255, 166, 48),
        (143, 92, 246), (255, 211, 57), (52, 198, 235), (244, 114, 182),
    ]
    background = palettes[index % len(palettes)]
    card = Image.new("RGBA", (560, 560), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    if index % 3 == 0:
        draw.ellipse((22, 22, 538, 538), fill=(*background, 255))
    elif index % 3 == 1:
        draw.rounded_rectangle((22, 22, 538, 538), radius=105, fill=(*background, 255))
    else:
        points = []
        centre = 280
        for point_index in range(24):
            angle = -3.14159265 / 2 + point_index * 3.14159265 / 12
            radius = 258 if point_index % 2 == 0 else 218
            points.append((centre + radius * math.cos(angle), centre + radius * math.sin(angle)))
        draw.polygon(points, fill=(*background, 255))

    icon = icon.convert("RGBA")
    icon.thumbnail((330, 330), Image.Resampling.LANCZOS)
    card.alpha_composite(icon, ((560 - icon.width) // 2, 62 + (330 - icon.height) // 2))
    labels = {
        "smiley-faces": ("GREAT JOB!", "KEEP SMILING!", "AMAZING!", "BRILLIANT!"),
        "well-done": ("WELL DONE!", "SUPER WORK!", "FANTASTIC!", "YOU DID IT!"),
        "youre-a-star": ("YOU'RE A STAR!", "SHINING STAR!", "STAR WORK!", "SO PROUD!"),
    }
    label = labels[category][index % len(labels[category])]
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 46 if len(label) < 12 else 37)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font, stroke_width=2)
    text_width = right - left
    draw.rounded_rectangle((38, 420, 522, 520), radius=45, fill=(255, 255, 255, 245))
    draw.text(((560 - text_width) / 2, 443), label, font=font, fill=(45, 55, 88), stroke_width=1, stroke_fill=(45, 55, 88))
    return make_sticker(card)


def generate_school_categories(output: Path, count: int, session: requests.Session, only: str | None = None):
    metadata_response = session.get(f"{OPENMOJI_BASE}/data/openmoji.json", timeout=(35, 60))
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    unsafe = ("alcohol", "beer", "wine", "cocktail", "cigarette", "smoking", "weapon", "gun", "knife", "bomb", "coffin")
    clean = [
        item for item in metadata
        if not item.get("skintone")
        and not any(word in item.get("annotation", "").lower() for word in unsafe)
    ]
    pools = {
        "smiley-faces": [item for item in clean if item.get("group") == "smileys-emotion" and item.get("subgroups", "").startswith("face-")],
        "well-done": [item for item in clean if item.get("group") in ("animals-nature", "activities", "food-drink")],
        "youre-a-star": [item for item in clean if item.get("group") in ("symbols", "travel-places", "objects", "extras-openmoji")],
    }
    results = []
    for category, label in SCHOOL_CATEGORIES.items():
        if only and category != only:
            continue
        category_directory = output / category
        category_directory.mkdir(parents=True, exist_ok=True)
        sources = []
        for item in pools[category]:
            if len(sources) >= count:
                break
            try:
                url = f"{OPENMOJI_BASE}/color/618x618/{item['hexcode']}.png"
                response = session.get(url, timeout=(35, 60))
                response.raise_for_status()
                icon = Image.open(io.BytesIO(response.content)).convert("RGBA")
                number = len(sources) + 1
                school_sticker(icon, category, number - 1).save(
                    category_directory / f"{number:03d}.webp", "WEBP", quality=86, method=6
                )
                sources.append({
                    "number": number,
                    "name": item.get("annotation", ""),
                    "hexcode": item["hexcode"],
                    "source": url,
                    "license": "OpenMoji CC BY-SA 4.0",
                })
                print(f"{label}: {number}/{count}", flush=True)
            except Exception:
                continue
        (category_directory / "SOURCES.json").write_text(json.dumps(sources, indent=2) + "\n")
        if len(sources) < count:
            raise RuntimeError(f"{label} produced only {len(sources)} stickers out of {count}")
        results.append({"id": category, "label": label, "count": len(sources), "preview": f"/sticker-images/{category}/001.webp"})
    return results


def collect_category(category: str, details: dict, output: Path, count: int, session: requests.Session):
    if DDGS is None:
        raise RuntimeError("Install ddgs before using online sticker search")
    category_directory = output / category
    category_directory.mkdir(parents=True, exist_ok=True)
    hashes = []
    sources = []
    seen_urls = set()
    seen_checksums = set()
    search = DDGS(timeout=18)

    def fetch_candidate(result):
        url = result.get("image") or ""
        raw = image_bytes(session, url)
        checksum = hashlib.sha256(raw).hexdigest()
        prepared = []
        for subject_index, subject in enumerate(prepare_subjects(raw), start=1):
            sticker = make_sticker(subject)
            prepared.append((subject_index, sticker, visual_hash(sticker)))
        return result, checksum, prepared

    for query in details["queries"]:
        if len(sources) >= count:
            break
        for image_type in ("transparent", "clipart"):
            if len(sources) >= count:
                break
            try:
                results = search.images(
                    query,
                    region="uk-en",
                    safesearch="on",
                    max_results=80,
                    backend="bing",
                    type_image=image_type,
                )
            except Exception as error:
                print(f"Search warning for {query}: {error}")
                continue

            candidates = []
            for result in results:
                url = result.get("image") or ""
                if not url or url in seen_urls:
                    continue
                result_text = f"{result.get('title', '')} {result.get('url', '')}".lower()
                blocked = ("bundle", "sticker-sheet", "sticker sheet", "wallpaper", "worksheet", "coloring", "colouring", "onesie", "bodysuit", "t-shirt", "shirt mockup", "mug mockup")
                if any(word in result_text for word in blocked):
                    continue
                seen_urls.add(url)
                candidates.append(result)

            executor = ThreadPoolExecutor(max_workers=12)
            futures = [executor.submit(fetch_candidate, result) for result in candidates]
            try:
                for future in as_completed(futures):
                    if len(sources) >= count:
                        break
                    try:
                        result, checksum, prepared = future.result()
                    except Exception:
                        continue
                    if checksum in seen_checksums:
                        continue
                    seen_checksums.add(checksum)
                    url = result.get("image") or ""
                    for subject_index, sticker, fingerprint in prepared:
                        if len(sources) >= count:
                            break
                        if any(fingerprint - previous <= 12 for previous in hashes):
                            continue
                        number = len(sources) + 1
                        destination = category_directory / f"{number:03d}.webp"
                        sticker.save(destination, "WEBP", quality=84, method=6)
                        hashes.append(fingerprint)
                        sources.append(
                            {
                                "number": number,
                                "search_query": query,
                                "title": result.get("title", ""),
                                "source_page": result.get("url", ""),
                                "image_url": url,
                                "subject_index": subject_index,
                                "sha256": checksum,
                            }
                        )
                        print(f"{details['label']}: {number}/{count}", flush=True)
            finally:
                for future in futures:
                    if not future.done():
                        future.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
            time.sleep(0.7)

    (category_directory / "SOURCES.json").write_text(json.dumps(sources, indent=2) + "\n")
    if len(sources) < count:
        raise RuntimeError(f"{details['label']} produced only {len(sources)} clean, different stickers out of {count}")
    return sources


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--category", choices=sorted({**CATEGORIES, **SCHOOL_CATEGORIES}))
    parser.add_argument("--school-only", action="store_true")
    args = parser.parse_args()
    if args.count < 1 or args.count > 150:
        raise ValueError("Sticker count must be between 1 and 150")
    args.output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
    )
    retry = Retry(total=4, connect=4, read=4, backoff_factor=1.2, status_forcelist=(429, 500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=12, pool_maxsize=12))
    if args.school_only and args.category:
        raise ValueError("Use either --school-only or --category, not both")
    selected = {} if args.school_only else ({args.category: CATEGORIES[args.category]} if args.category in CATEGORIES else ({} if args.category else CATEGORIES))
    index = {"stickers_per_category": args.count, "categories": []}
    for category, details in selected.items():
        sources = collect_category(category, details, args.output, args.count, session)
        index["categories"].append(
            {
                "id": category,
                "label": details["label"],
                "count": len(sources),
                "preview": f"/sticker-images/{category}/001.webp",
            }
        )
    if args.school_only or args.category is None or args.category in SCHOOL_CATEGORIES:
        school_results = generate_school_categories(args.output, args.count, session, args.category)
        index["categories"].extend(school_results)
    (args.output / "index.json").write_text(json.dumps(index, indent=2) + "\n")


if __name__ == "__main__":
    main()
