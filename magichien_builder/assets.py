from itertools import groupby
import logging
import re

from PIL import Image

from .config import number


logger = logging.getLogger(__name__)
SPLIT_GUIDANCE = "Place each digit in its own column, sufficiently spaced apart (including shadows)."


class AssetCleaner:
    """Crop export watermarks, then remove transparent outer margins."""

    def __init__(self, settings):
        self.settings = settings

    def clean(self, image, filename):
        options = {**self.settings, **self.settings.get("assets", {}).get(filename, {})}
        box = options.get("crop", [0, 0, 1, 1])
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError(f"{filename}: crop must be [left, top, right, bottom]")
        left, top, right, bottom = [number(v, "crop") for v in box]
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError(f"{filename}: crop must be ordered and within 0..1")
        pixel_box = tuple(round(v * (image.width if i % 2 == 0 else image.height))
                          for i, v in enumerate(box))
        image = image.convert("RGBA").crop(pixel_box)
        bounds = image.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError(f"{filename}: cleanup produced an empty image")
        return image.crop(bounds) if options.get("trim", True) else image


def split_digits(image, threshold=32, boundaries=None, filename="number sheet"):
    threshold = number(threshold, "detection_alpha")
    if not 0 <= threshold < 255:
        raise ValueError("detection_alpha must be within 0..254")
    alpha = image.getchannel("A")
    columns = [alpha.crop((x, 0, x + 1, image.height)).getextrema()[1]
               for x in range(image.width)]
    if boundaries is None:
        runs = [list(group) for active, group in
                groupby(range(image.width), lambda x: columns[x] > threshold) if active]
        if len(runs) != 10:
            raise ValueError(f"Found {len(runs)} digits, expected 10 (1234567890); set digits.split_boundaries for this sheet")
        boundaries = [(a[-1] + 1 + b[0]) // 2 for a, b in zip(runs, runs[1:])]
    if not isinstance(boundaries, (list, tuple)) or len(boundaries) != 9:
        raise ValueError("Digit split_boundaries must contain nine pixel coordinates")
    if any(isinstance(x, bool) or not isinstance(x, int) for x in boundaries):
        raise ValueError("Digit split boundaries must be whole pixels")
    edges = [0, *boundaries, image.width]
    if any(a >= b for a, b in zip(edges, edges[1:])):
        raise ValueError("Digit split boundaries must increase within the cleaned sheet")
    if any(max(columns[x - 1], columns[x]) > 0 for x in boundaries):
        logger.warning("%s: numbers cannot be cleanly split because contours or shadows overlap; "
                       "using approximate column crops. %s", filename, SPLIT_GUIDANCE)
    digits = {}
    for label, (left, right) in zip("1234567890", zip(edges, edges[1:])):
        digit = image.crop((left, 0, right, image.height))
        bounds = digit.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError(f"Digit {label} is empty")
        # Trim horizontal padding only, keeping the sheet's shared baseline.
        digits[label] = digit.crop((bounds[0], 0, bounds[2], digit.height))
    return digits


def discover_cards(paths, background=None):
    cards = []
    for path in sorted(paths):
        if path == background or path.stem.startswith(("FRAME_", "NUMBERS_")):
            continue
        match = re.fullmatch(r"(.+?)_(NN.*|[0-9]+)", path.stem)
        if match:
            family, value = match.groups()
            cards.append((path.stem, family, None if value.startswith("NN") else value))
    return cards
