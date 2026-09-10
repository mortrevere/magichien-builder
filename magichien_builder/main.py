import argparse
from html import escape
from itertools import groupby
import logging
from pathlib import Path
import sys
import tarfile
from urllib.parse import quote

from PIL import Image, ImageOps
import yaml

from .assets import AssetCleaner, SPLIT_GUIDANCE, discover_cards, split_digits
from .config import dimensions, layout_for, load_config, number, pair


logger = logging.getLogger(__name__)


def fitted(image, box, scale=1):
    scale = number(scale, "scale", positive=True)
    factor = min(box[0] / image.width, box[1] / image.height) * scale
    return image.resize(tuple(max(1, round(v * factor)) for v in image.size), Image.Resampling.LANCZOS)


def position(center, origin, size):
    return tuple(o + c * s for c, o, s in zip(pair(center, "center"), origin, size))


def overlay(canvas_size, image, center):
    layer = Image.new("RGBA", canvas_size)
    xy = tuple(round(c - s / 2) for c, s in zip(center, image.size))
    layer.alpha_composite(image, xy)
    return layer, xy


def number_image(value, digits, height, spacing):
    missing = set(value) - digits.keys()
    if missing:
        raise ValueError(f"Number {value} requires missing glyphs: {', '.join(sorted(missing))}")
    gap = round(number(spacing, "number spacing") * height)
    if gap < 0:
        raise ValueError("Number spacing cannot be negative")
    # Exported digits have different vertical padding; align their visible bounds.
    glyphs = [digits[d].crop(digits[d].getchannel("A").getbbox()) for d in value]
    glyphs = [glyph.resize((max(1, round(glyph.width * height / glyph.height)), height),
                           Image.Resampling.LANCZOS) for glyph in glyphs]
    result = Image.new("RGBA", (sum(g.width for g in glyphs) + gap * (len(glyphs) - 1), height))
    x = 0
    for glyph in glyphs:
        result.alpha_composite(glyph, (x, 0))
        x += glyph.width + gap
    return result


def render_card(subject, frame, digits, value, background, card, layout):
    trim, full, offset, dpi = dimensions(card)
    if background is None:
        base = Image.new("RGBA", full)
    else:
        base = ImageOps.fit(background, full, method=Image.Resampling.LANCZOS)
    frame_box = tuple(a * b for a, b in zip(pair(layout["frame"]["size"], "frame size", True), trim))
    frame = fitted(frame, frame_box)
    frame_layer, frame_origin = overlay(full, frame, position(layout["frame"]["center"], offset, trim))
    settings = layout["subject"]
    subject_box = tuple(a * b for a, b in zip(pair(settings["size"], "subject size", True), frame.size))
    subject = fitted(subject, subject_box, settings.get("scale", 1))
    subject_layer, _ = overlay(full, subject, position(settings["center"], frame_origin, frame.size))
    numbers = Image.new("RGBA", full)
    if value is not None:
        settings = layout["numbers"]
        height = max(1, round(number(settings["height"], "number height", True) * frame.height))
        label = number_image(value, digits, height, settings.get("spacing", 0))
        width = label.width
        if "max_width" in settings:
            width = number(settings["max_width"], "number max_width", True) * frame.width
            if label.width > width:
                label = fitted(label, (width, height))
        for placement in settings["placements"]:
            rotation = number(placement.get("rotation", 0), "rotation")
            rotated = label.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
            x, y = position(placement["center"], frame_origin, frame.size)
            alignment = {"left": -1, "center": 0, "right": 1}[placement.get("align", "center")]
            x += alignment * (width - rotated.width) / 2
            layer, _ = overlay(full, rotated, (x, y))
            numbers = Image.alpha_composite(numbers, layer)
    layers = {"01-background": base, "02-subject": subject_layer,
              "03-frame": frame_layer, "04-numbers": numbers}
    result = base.copy()
    for layer in (subject_layer, frame_layer, numbers):
        result = Image.alpha_composite(result, layer)
    return result, layers, dpi


def write_catalog(cards, directory):
    cards = sorted(cards, key=lambda card: (card[2] is not None, card[1],
                                           int(card[2]) if card[2] is not None else 0, card[0]))
    lines = ["# Cards", "", f"{len(cards)} rendered cards. Special cards first, then families in numeric order.", ""]
    page = ['''<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Magichien — Cards</title>
<style>
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 24px; max-width: 1400px; background: #f5f3ee;
       color: #292723; font: 16px system-ui, sans-serif; }
header { display: flex; align-items: baseline; justify-content: space-between;
         gap: 16px; flex-wrap: wrap; margin-bottom: 40px; }
h1 { margin: 0; font-size: 24px; } h2 { font-size: 16px; font-weight: 500; }
a { color: inherit; text-underline-offset: 4px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
         gap: 24px 16px; margin-bottom: 40px; }
figure { margin: 0; } img { display: block; width: 100%; height: auto; }
figcaption { margin-top: 8px; font-size: 12px; color: #615d54; }
a:focus-visible { outline: 3px solid #79612a; outline-offset: 4px; }
html:has(#gallery[open]) { overflow: hidden; }
#gallery { position: fixed; inset: 0; width: 100%; height: 100%; max-width: none;
           max-height: none; margin: 0; padding: 48px 16px; border: 0;
           background: #171614; color: white; }
#gallery img { width: 100%; height: 100%; object-fit: contain; }
#gallery button { position: absolute; border: 0; color: inherit; background: transparent;
                  cursor: pointer; font: 32px system-ui, sans-serif; }
#gallery button:focus-visible { outline: 3px solid white; outline-offset: -4px; }
#previous, #next { top: 0; bottom: 0; width: 50%; padding: 16px;
                    text-shadow: 0 1px 4px black; }
#previous { left: 0; text-align: left; }
#next { right: 0; text-align: right; }
#gallery #close { top: 0; right: 0; width: 48px; height: 48px; background: #171614; }
#gallery-caption { position: absolute; bottom: 12px; left: 0; width: 100%; margin: 0;
                     text-align: center; pointer-events: none; font-size: 14px; }
</style>
<header><h1>Magichien</h1><a href="rendered-cards.tar.gz" download>Download all cards</a></header>
<main>''']
    for group, members in groupby(cards, key=lambda card: "Special cards" if card[2] is None else card[1]):
        members = list(members)
        lines.extend([f"## {escape(group)}", "", "| Card | Preview |", "| --- | --- |"])
        page.append(f'<section><h2>{escape(group)} ({len(members)})</h2><div class="cards">')
        for stem, _, _ in members:
            label = escape(stem).replace("|", "&#124;")
            lines.append(f'| {label} | <img src="{quote(stem + ".png")}" alt="{label}" width="180"> |')
            page.append(f'<figure><a href="{quote(stem + ".png")}">'
                        f'<img src="previews/{quote(stem + ".webp")}" alt="{label}" '
                        f'loading="lazy" decoding="async"></a><figcaption>{label}</figcaption></figure>')
        lines.append("")
        page.append('</div></section>')
    (directory / "CARDS.md").write_text("\n".join(lines), encoding="utf-8")
    page.append('''</main>
<dialog id="gallery" aria-label="Card gallery">
<img id="gallery-image" alt="">
<button id="previous" type="button" aria-label="Previous card">&#8249;</button>
<button id="next" type="button" aria-label="Next card">&#8250;</button>
<button id="close" type="button" aria-label="Close gallery" autofocus>&times;</button>
<p id="gallery-caption" aria-live="polite"></p>
</dialog>
<script>
const links = [...document.querySelectorAll('.cards a')];
const gallery = document.getElementById('gallery');
const galleryImage = document.getElementById('gallery-image');
const caption = document.getElementById('gallery-caption');
let current = 0;
function showCard(index) {
  current = (index + links.length) % links.length;
  galleryImage.src = links[current].href;
  galleryImage.alt = links[current].querySelector('img').alt;
  caption.textContent = `${galleryImage.alt} (${current + 1} / ${links.length})`;
}
links.forEach((link, index) => link.addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  showCard(index);
  gallery.showModal();
}));
document.getElementById('previous').addEventListener('click', () => showCard(current - 1));
document.getElementById('next').addEventListener('click', () => showCard(current + 1));
document.getElementById('close').addEventListener('click', () => gallery.close());
gallery.addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault();
    showCard(current + (event.key === 'ArrowLeft' ? -1 : 1));
  }
});
</script>
</html>''')
    (directory / "index.html").write_text("\n".join(page), encoding="utf-8")


def build(config, process_only=False):
    paths = config["paths"]
    sources = sorted(p for p in paths["assets"].glob("*") if p.suffix.lower() == ".png" and p.is_file())
    if not sources:
        raise ValueError(f"No PNG assets found in {paths['assets']}")
    background_path = config.get("background")
    if background_path and background_path not in sources:
        raise ValueError("Background must be a PNG directly inside the assets directory")
    # Generated directories must never coincide with or contain source assets.
    for output in (paths["processed"], paths["rendered"]):
        if output == paths["assets"] or output in paths["assets"].parents:
            raise ValueError("Output directories cannot contain the source assets directory")
    cleaner = AssetCleaner(config["cleanup"])
    cleaned = {}
    filenames = {path.stem: path.name for path in sources}
    sheets = {}
    for path in sources:
        with Image.open(path) as image:
            cleaned[path.stem] = cleaner.clean(image, path.name)
        if path.stem.startswith("NUMBERS_"):
            try:
                sheets[path.stem[8:]] = split_digits(
                    cleaned[path.stem], config["digits"].get("detection_alpha", 32),
                    config["digits"].get("split_boundaries", {}).get(path.name), path.name)
            except ValueError as error:
                logger.warning("%s: numbers cannot be cleanly split: %s. %s "
                               "Cards requiring this sheet will be skipped.", path.name, error, SPLIT_GUIDANCE)
    cards = discover_cards(sources, background_path)
    if not process_only:
        if not cards:
            raise ValueError("No card subjects matched <FAMILY>_<number> or <FAMILY>_NN*")
        ready = []
        for stem, family, value in cards:
            if f"FRAME_{family}" not in cleaned:
                raise ValueError(f"{stem}: missing FRAME_{family}.png")
            if value is not None:
                if family not in sheets:
                    logger.warning("Skipping %s: missing or unusable NUMBERS_%s.png", stem, family)
                    continue
                if missing := set(value) - sheets[family].keys():
                    logger.warning("Skipping %s: missing number glyphs: %s", stem, ', '.join(sorted(missing)))
                    continue
            ready.append((stem, family, value))
        logger.info("Skipped %d cards with unavailable numbers", len(cards) - len(ready))
        cards = ready
    for stem, image in cleaned.items():
        target = paths["processed"] / "cleaned" / f"{stem}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
    for family, digits in sheets.items():
        target = paths["processed"] / "digits" / family
        target.mkdir(parents=True, exist_ok=True)
        for digit, image in digits.items():
            image.save(target / f"{digit}.png")
    print(f"Processed {len(cleaned)} assets and {sum(map(len, sheets.values()))} digits: {paths['processed']}")
    if process_only:
        return []
    background = cleaned[background_path.stem] if background_path else None
    outputs = []
    paths["rendered"].mkdir(parents=True, exist_ok=True)
    previews = paths["rendered"] / "previews"
    previews.mkdir(exist_ok=True)
    for stem, family, value in cards:
        result, layers, dpi = render_card(cleaned[stem], cleaned[f"FRAME_{family}"],
                                          sheets.get(family, {}), value, background,
                                          config["card"], layout_for(config, family, filenames[stem]))
        target = paths["processed"] / "layers" / stem
        target.mkdir(parents=True, exist_ok=True)
        for name, layer in layers.items():
            layer.save(target / f"{name}.png", dpi=(dpi, dpi))
        output = paths["rendered"] / f"{stem}.png"
        result.save(output, dpi=(dpi, dpi))
        result.thumbnail((360, 510), Image.Resampling.LANCZOS)
        result.save(previews / f"{stem}.webp", quality=85)
        outputs.append(output)
    write_catalog(cards, paths["rendered"])
    archive_files = [*outputs, *(previews / f"{stem}.webp" for stem, _, _ in cards),
                     paths["rendered"] / "CARDS.md", paths["rendered"] / "index.html"]
    with tarfile.open(paths["rendered"] / "rendered-cards.tar.gz", "w:gz") as archive:
        for output in archive_files:
            archive.add(output, arcname=output.relative_to(paths["rendered"]))
    print(f"Rendered {len(outputs)} cards: {paths['rendered']}")
    return outputs


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Render a printable PNG card deck from YAML and assets.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--process-only", action="store_true", help="Clean assets and split digits without rendering cards")
    args = parser.parse_args()
    try:
        build(load_config(args.config), args.process_only)
    except (ValueError, OSError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
