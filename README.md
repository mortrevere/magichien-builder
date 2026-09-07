# Magichien Builder

Compose a printable card deck from transparent PNG subjects, frames and number sheets.
Python 3.12 and uv are required.

```sh
uv sync --locked
uv run magichien-builder --config config.yaml
uv run magichien-builder --config config.yaml --process-only
uv run python -m unittest discover -s tests
```

All paths in the YAML are relative to that configuration file. Source files are
never modified. Only PNG files directly inside `assets/` are processed; nested
directories are ignored. Each build reads the originals, so edits to the YAML
are reflected immediately. Existing generated files with matching names are
replaced; unrelated or obsolete outputs are not deleted automatically.

## Asset names

- `GREEN_5.png` uses `FRAME_GREEN.png` and digit 5 from `NUMBERS_GREEN.png`.
- `WOAF_NN1.png` uses `FRAME_WOAF.png`, without an added number.
- Families are arbitrary names, not a fixed list of colors.
- Number sheets must contain all ten digits `1234567890` in a single row,
  with zero last. Multi-digit values are composed from these glyphs.
  Cards requiring unavailable glyphs
  or missing/unusable sheets are skipped with a warning; other cards render.
- Backgrounds and reference images do not become cards. Other PNGs become
  cards only when their names match `<FAMILY>_<number>` or `<FAMILY>_NN*`.

## Print settings

The default `card` settings are `size_mm: [63, 89]`, `dpi: 300`, and
`bleed_mm: 3`. The trim area is 744x1051 pixels; the full PNG is 815x1122
pixels. Opposing bleed margins can differ by one pixel due to rounding.
Print at the embedded DPI, with automatic page fitting disabled.

To specify pixels, replace `size_mm` with `size_px: [744, 1051]`.
Do not specify both. DPI defaults to 300 and controls physical bleed conversion
even in pixel mode. Set `bleed_mm: 0` for exact trim-sized exports.
The background covers the full bleed canvas; artwork positions use the trim
area. There are no crop marks or PDF sheets.

## Cleanup and layout

`cleanup.crop` is `[left, top, right, bottom]` in fractions of each source
image. The supplied exports retain the top 92%, removing the watermark.
This is a calibrated crop, not automatic watermark recognition: adjust it for
new exports whose artwork or watermark occupies a different region.
`cleanup.assets` overrides crop and `trim` by exact filename. The supplied
background retains its entire image. Set `background: null` for transparency.

Digit detection uses `digits.detection_alpha` only to locate boundaries; the
output retains original alpha values. Overlapping shadows produce a warning
and are divided with approximate column crops; faint neighboring shadow
fragments may remain because the original glyphs overlap. For clean splitting,
place each digit in its own column, sufficiently spaced apart including its
shadow. Sheets that cannot be split into ten digits produce a warning; their
dependent cards are skipped. To correct a sheet manually,
set `digits.split_boundaries.NUMBERS_GREEN.png` to nine increasing x pixel coordinates measured in its
**cleaned** image. Extracted digits share the
sheet's vertical extent to retain alignment.

Frame `center` and `size` are fractions of the trim canvas. The frame fits its
box without changing proportions. Subject `center` and `size` are fractions
of the **fitted frame**, and `scale` multiplies its proportional fit. Number
`height` is a fraction of frame height; `spacing` is a fraction of number
height. Placement centers are relative to the fitted frame, and rotations are
counterclockwise degrees. Composition order is background, subject, frame,
numbers. Oversized or off-center layers are clipped at the output canvas.

Global `layout` fields can be overridden by `families` and then by `cards`,
whose keys are exact source filenames including the extension.
Fields are merged within each section; a placement list is replaced in full:

```yaml
families:
  GREEN:
    numbers:
      height: 0.12
cards:
  GREEN_5.png:
    subject:
      center: [0.48, 0.49]
      scale: 0.95
```

## Outputs

- `assets/processed/cleaned/`: cropped, alpha-trimmed source assets.
- `assets/processed/digits/<FAMILY>/`: individual 0-9 glyphs.
- `assets/processed/layers/<CARD>/`: positioned background, subject, frame
  and numbers as separate full-canvas PNGs.
- `rendered/<CARD>.png`: composed card fronts with DPI metadata.
- `rendered/CARDS.md`: gallery of the cards rendered by this build, with special
  (`NN*`) cards first, then families alphabetically and values numerically.
  Image links are relative, so keep the gallery alongside the PNGs.
  `--process-only` does not generate or update the gallery.

## GitHub Actions

The `Render cards` workflow tests and rebuilds the deck on every push to `main`
(including merges), and can also be run manually from the Actions tab.
Download `rendered-cards` from the completed run's artifacts and extract it to
view `CARDS.md` with its PNGs in a Markdown viewer. Generated files are uploaded
using [upload-artifact](https://github.com/actions/upload-artifact); they are
not committed back to the repository. No custom secrets are needed.

Dependencies are Pillow and PyYAML. Tests use Python's standard library.
