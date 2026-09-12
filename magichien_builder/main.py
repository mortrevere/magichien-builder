import argparse
from concurrent.futures import ThreadPoolExecutor
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
from .pdf import check_safe_margin, prepare_pdf, safe_area, write_pdf


logger = logging.getLogger(__name__)


def fitted(image, box, scale=1):
    scale = number(scale, "scale", positive=True)
    factor = min(box[0] / image.width, box[1] / image.height) * scale
    return image.resize(tuple(max(1, round(v * factor)) for v in image.size), Image.Resampling.LANCZOS)


def position(center, origin, size):
    return tuple(o + c * s for c, o, s in zip(pair(center, "center"), origin, size))


def overlay(canvas_size, image, center, safe_box=None):
    layer = Image.new("RGBA", canvas_size)
    xy = tuple(round(c - s / 2) for c, s in zip(center, image.size))
    bounds = image.getchannel("A").getbbox()
    if safe_box and bounds:
        left, top, right, bottom = safe_box
        if (xy[0] + bounds[0] < left or xy[1] + bounds[1] < top or
                xy[0] + bounds[2] > right or xy[1] + bounds[3] > bottom):
            raise ValueError("Artwork enters the safety margin (checked before canvas clipping)")
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
    safe_box = safe_area(card) if card.get("safe_margin_mm") is not None else None
    if background is None:
        base = Image.new("RGBA", full)
    else:
        base = ImageOps.fit(background, full, method=Image.Resampling.LANCZOS)
    frame_box = tuple(a * b for a, b in zip(pair(layout["frame"]["size"], "frame size", True), trim))
    frame = fitted(frame, frame_box)
    frame_layer, frame_origin = overlay(full, frame, position(layout["frame"]["center"], offset, trim), safe_box)
    settings = layout["subject"]
    subject_box = tuple(a * b for a, b in zip(pair(settings["size"], "subject size", True), frame.size))
    subject = fitted(subject, subject_box, settings.get("scale", 1))
    subject_layer, _ = overlay(full, subject, position(settings["center"], frame_origin, frame.size), safe_box)
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
            layer, _ = overlay(full, rotated, (x, y), safe_box)
            numbers = Image.alpha_composite(numbers, layer)
    layers = {"01-background": base, "02-subject": subject_layer,
              "03-frame": frame_layer, "04-numbers": numbers}
    result = base.copy()
    for layer in (subject_layer, frame_layer, numbers):
        result = Image.alpha_composite(result, layer)
    return result, layers, dpi


def card_order(card):
    return card[2] is not None, card[1], int(card[2]) if card[2] is not None else 0, card[0]


def write_catalog(cards, directory, back=False, pdf=False):
    cards = sorted(cards, key=card_order)
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
<header><h1>Magichien</h1><div>Download all cards:
<a href="rendered-cards.tar.gz" download>tar.gz</a>''']
    if pdf:
        page.append(' · <a href="rendered-cards.pdf" download>PDF</a>')
    page.append('</div></header><main>')
    groups = [(group, list(members)) for group, members in groupby(
        cards, key=lambda card: "Special cards" if card[2] is None else card[1])]
    if back:
        groups.insert(0, ("Shared back", [("BACK", "", None)]))
    for group, members in groups:
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
    back_path = config.get("back")
    if back_path and back_path not in sources:
        raise ValueError("Back must be a PNG directly inside the assets directory")
    if back_path and back_path == background_path:
        raise ValueError("Back and background must be different images")
    pdf_enabled = config.get("pdf") is not None and not process_only
    if pdf_enabled and not back_path:
        raise ValueError("PDF export requires a shared back")
    pdf_settings = prepare_pdf(config) if pdf_enabled else None
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
    cards = discover_cards([p for p in sources if p != back_path], background_path)
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
        if pdf_enabled and len(cards) != len(ready):
            skipped = sorted(set(c[0] for c in cards) - set(c[0] for c in ready))
            raise ValueError("Cannot export an incomplete PDF; skipped cards: " + ", ".join(skipped))
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
    render_settings = dict(config["card"])
    if pdf_enabled:
        render_settings.setdefault("safe_margin_mm", 4)
    background = cleaned[background_path.stem] if background_path else None
    paths["rendered"].mkdir(parents=True, exist_ok=True)
    previews = paths["rendered"] / "previews"
    previews.mkdir(exist_ok=True)

    def export_card(stem, result, layers, dpi):
        if pdf_enabled:
            check_safe_margin(stem, layers, config["card"])
        target = paths["processed"] / "layers" / stem
        target.mkdir(parents=True, exist_ok=True)
        for name, layer in layers.items():
            layer.save(target / f"{name}.png", dpi=(dpi, dpi))
        output = paths["rendered"] / f"{stem}.png"
        result.save(output, dpi=(dpi, dpi))
        result.thumbnail((360, 510), Image.Resampling.LANCZOS)
        result.save(previews / f"{stem}.webp", quality=85)
        return output

    def build_card(card):
        stem, family, value = card
        try:
            return export_card(stem, *render_card(
                cleaned[stem], cleaned[f"FRAME_{family}"], sheets.get(family, {}), value, background,
                render_settings, layout_for(config, family, filenames[stem])))
        except ValueError as error:
            raise ValueError(f"{stem}: {error}") from error

    with ThreadPoolExecutor(max_workers=8) as workers:
        outputs = list(workers.map(build_card, cards))
    archive_files = [*outputs, *(previews / f"{stem}.webp" for stem, _, _ in cards),
                     paths["rendered"] / "CARDS.md", paths["rendered"] / "index.html"]
    if back_path:
        # The back is already a complete design: reuse frame placement without a subject or numbers.
        transparent = Image.new("RGBA", (1, 1))
        back_output = export_card("BACK", *render_card(
            transparent, cleaned[back_path.stem], {}, None, background, render_settings,
            layout_for(config, "BACK", back_path.name)))
        archive_files.extend([back_output, previews / "BACK.webp"])
    if pdf_enabled:
        pdf_path = paths["rendered"] / "rendered-cards.pdf"
        ordered = [paths["rendered"] / f"{stem}.png" for stem, _, _ in sorted(cards, key=card_order)]
        write_pdf([back_output, *ordered], pdf_path, config["card"], pdf_settings)
        archive_files.append(pdf_path)
    write_catalog(cards, paths["rendered"], back=bool(back_path), pdf=pdf_enabled)
    with tarfile.open(paths["rendered"] / "rendered-cards.tar.gz", "w:gz") as archive:
        for output in archive_files:
            archive.add(output, arcname=output.relative_to(paths["rendered"]))
    print(f"Rendered {len(outputs)} cards: {paths['rendered']}")
    return outputs


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Render a PNG card deck and optional print PDF from YAML and assets.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--process-only", action="store_true", help="Clean assets and split digits without rendering cards")
    args = parser.parse_args()
    try:
        build(load_config(args.config), args.process_only)
    except (ValueError, OSError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
