# Magichien Builder

**[Browse the cards →](https://mortrevere.github.io/magichien-builder/)**

Create printable Magichien cards from artwork, frames, and number sheets.
The gallery shows special cards first, then each family in numeric order.
Click a card to open its full-resolution PNG, or choose **Download all cards**
to get the whole deck. No installation is needed to browse or download.

## Build your own deck

Install Python 3.12 and uv, then run from this repository:

```sh
uv sync --locked
uv run magichien-builder --config config.yaml
```

Cards render and export eight at a time. Open `preview/index.html` in your
browser to see the result. You'll also find:

- `preview/<CARD>.png`: full-resolution card fronts, ready to print.
- `preview/CARDS.md`: a Markdown gallery.
- `preview/rendered-cards.tar.gz`: the complete deck, galleries, and web previews.
  Extract it and open `index.html` to browse offline.

To change the deck, edit [config.yaml](config.yaml) or replace the source
artwork, then run the build again. Your source images are never modified.

## Add cards

Put transparent PNG artwork directly in `assets/`. Subfolders are ignored.
Use matching family names for the artwork, frame, and number sheet:

| Card type | Artwork | Frame | Number sheet |
| --- | --- | --- | --- |
| Numbered card | `GREEN_5.png` | `FRAME_GREEN.png` | `NUMBERS_GREEN.png` |
| Special card, without a number | `WOAF_NN1.png` | `FRAME_WOAF.png` | Not needed |

Choose any family name. Numbered cards use `<FAMILY>_<number>.png`; special
cards use `<FAMILY>_NN*.png`. Backgrounds and reference images aren't cards.
Each number sheet must contain **1234567890**, in that order, in one row.
Leave space between digits, including their shadows. Values such as 10 or 12
are assembled automatically.

## Configure the cards

[config.yaml](config.yaml) controls print size, image cleanup, and placement.
All file paths are relative to the configuration file. The main settings are:

| Setting | What you can change |
| --- | --- |
| `card` | Card dimensions, print resolution, and bleed |
| `background` | Background image; use `null` for transparency |
| `cleanup` | Crop source images and trim transparent margins |
| `layout` | Position and size of the frame, artwork, and numbers |
| `families` | Layout adjustments for every card in one family |
| `cards` | Layout adjustments for a single source filename |
| `paths` | Source, intermediate, and final output directories |

### Print size

The supplied configuration makes **63 × 89 mm cards at 300 DPI**, with
**3 mm bleed** around each edge. Each full PNG is 815 × 1122 pixels.
Print at the embedded DPI with automatic page fitting disabled.
Exports are individual card fronts; there are no PDF sheets or crop marks.

```yaml
card:
  size_mm: [63, 89]
  dpi: 300
  bleed_mm: 3
```

For exact pixel dimensions, replace `size_mm` with `size_px: [744, 1051]`;
use only one of these settings. Set `bleed_mm: 0` to export without bleed.

### Adjust artwork and numbers

Start with `layout` for changes across the deck. Use `families` or `cards`
for exceptions. For example, this makes GREEN numbers smaller and adjusts
only the artwork on GREEN_5:

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

Positions and sizes are fractions: `[0.5, 0.5]` is the center. Frame settings
are relative to the trimmed card; artwork and number settings are relative
to the fitted frame. `scale` enlarges or shrinks artwork without changing its
proportions. Number rotations are counterclockwise degrees.
Digits are aligned and sized by their visible bounds. `numbers.max_width`
caps the complete label width as a fraction of the fitted frame, shrinking
wide labels proportionally to keep them inside the corners.
Each placement can set `align: left`, `center` (the default), or `right`
within that width, after rotation. The supplied top-left and bottom-right
placements are independently positioned and edge-aligned to their frame details.

Card settings take precedence over family settings, which take precedence
over the global layout. Only the fields you supply are overridden; a number
placement list replaces the whole list. Layers are drawn as background,
artwork, frame, then numbers, with anything outside the canvas clipped.

### Crop and clean source images

`cleanup.crop` uses `[left, top, right, bottom]` as fractions of the source
image. The supplied `[0, 0, 1, 0.92]` keeps the top 92% to remove the watermark
on these exports. Adjust it for artwork with different margins.
Use `cleanup.assets` with an exact filename to override its crop or `trim`.
The supplied background keeps its full image.

To inspect cleanup and extracted digits without rendering the deck:

```sh
uv run magichien-builder --config config.yaml --process-only
```

Look in `assets/processed/cleaned/` and `assets/processed/digits/`.
A full build also saves each card's separate layers in
`assets/processed/layers/`. These intermediate files are ignored by Git.

If a number sheet can't be split into ten digits, affected cards are skipped
with a warning. Overlapping shadows may leave fragments on neighboring
numbers. Space the source digits farther apart, or set
`digits.split_boundaries.NUMBERS_GREEN.png` to nine increasing x coordinates
measured in the **cleaned** sheet. `digits.detection_alpha` controls boundary
detection without changing the glyphs' transparency.

## Publish changes

Push or merge changes to `main` to rebuild and publish the
[live gallery](https://mortrevere.github.io/magichien-builder/).
The workflow commits the generated cards and galleries in `preview/` back to
`main`, makes the archive available to download, and deploys the site to
GitHub Pages. You can follow progress or start a build manually in
[Actions](https://github.com/mortrevere/magichien-builder/actions).
Tests run on pull requests only.

For a fork, select **Settings → Pages → Source → GitHub Actions** once.
Repository rules must allow the workflow to push generated files to `main`.
No custom secrets are needed.

Local builds replace matching outputs but leave old files in place. The
publishing workflow rebuilds `preview/` from scratch, so removed cards also
disappear from the published site. Keep `paths.rendered` and the workflow's
`preview/` paths in sync if you change the output directory.

## Development

The builder uses Pillow and PyYAML. Run the test suite with:

```sh
uv run python -m unittest discover -s tests
```
