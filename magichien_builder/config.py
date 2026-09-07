from copy import deepcopy
from pathlib import Path
import math

import yaml


def pair(value, name, positive=False):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must contain two numbers")
    return tuple(number(v, name, positive=positive) for v in value)


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return value


def dimensions(card):
    dpi = number(card.get("dpi", 300), "dpi", positive=True)
    bleed = number(card.get("bleed_mm", 3), "bleed_mm")
    if bleed < 0:
        raise ValueError("bleed_mm cannot be negative")
    if ("size_mm" in card) == ("size_px" in card):
        raise ValueError("Specify exactly one of card.size_mm and card.size_px")
    if "size_mm" in card:
        mm = pair(card["size_mm"], "size_mm", positive=True)
        exact = tuple(v * dpi / 25.4 for v in mm)
    else:
        exact = pair(card["size_px"], "size_px", positive=True)
        if any(int(v) != v for v in exact):
            raise ValueError("size_px must contain whole pixels")
    trim = tuple(round(v) for v in exact)
    full = tuple(round(v + 2 * bleed * dpi / 25.4) for v in exact)
    if min(trim) < 1:
        raise ValueError("Card dimensions must produce at least one pixel")
    offset = tuple((f - t) // 2 for f, t in zip(full, trim))
    return trim, full, offset, dpi


def load_config(path):
    path = Path(path).resolve()
    with path.open() as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    for key in ("paths", "card", "cleanup", "digits", "layout"):
        if not isinstance(config.get(key), dict):
            raise ValueError(f"{key} must be a mapping")
    dimensions(config["card"])
    for key in ("assets", "processed", "rendered"):
        config["paths"][key] = (path.parent / config["paths"][key]).resolve()
    if config.get("background"):
        config["background"] = (path.parent / config["background"]).resolve()
    return config


def layout_for(config, family, filename):
    layout = deepcopy(config["layout"])
    for override in (config.get("families", {}).get(family, {}),
                     config.get("cards", {}).get(filename, {})):
        for section, fields in override.items():
            if section not in layout or not isinstance(fields, dict):
                raise ValueError(f"Invalid layout override: {section}")
            layout[section].update(fields)
    return layout
