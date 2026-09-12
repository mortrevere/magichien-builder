# Magichien Builder

**[Browse the cards →](https://mortrevere.github.io/magichien-builder/)**

Create printable Magichien cards from artwork, frames, and number sheets.
The gallery shows the shared back, special cards, then each family in numeric order.
Click a card to open its full-resolution PNG, or choose **tar.gz** or **PDF**
under **Download all cards**. No installation is needed to browse or download.

## Build your own deck

Install Python 3.12 and uv, then run from this repository:

```sh
uv sync --locked
uv run python scripts/fetch-print-profile.py
uv run magichien-builder --config config.yaml
```

The profile download is a one-time setup step. The ICC file stays locally in
`assets/profiles/`, ignored by Git; subsequent builds work offline. The setup
script verifies its checksum and reuses an already installed profile.

Cards render and export eight at a time. Open `preview/index.html` in your
browser to see the result. You'll also find:

- `preview/<CARD>.png`: full-resolution RGB card fronts.
- `preview/BACK.png`: the shared back, composited over the same background.
- `preview/rendered-cards.pdf`: the CMYK print deck, back first, one face per page.
- `preview/CARDS.md`: a Markdown gallery.
- `preview/rendered-cards.tar.gz`: the PNGs, PDF, galleries, and web previews.
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
| `card` | Card dimensions, print resolution, bleed, and safety margin |
| `background` | Background image; use `null` for transparency |
| `back` | Shared back artwork; omit it for a front-only PNG build |
| `pdf` | CMYK output profile; omit this section or set it to `null` for PNG-only builds |
| `cleanup` | Crop source images and trim transparent margins |
| `layout` | Position and size of the frame, artwork, and numbers |
| `families` | Layout adjustments for every card in one family |
| `cards` | Layout adjustments for a single source filename |
| `paths` | Source, intermediate, and final output directories |

### Print size

The supplied configuration makes **63 × 89 mm cards at 300 DPI**, with
**2.5 mm bleed** around each edge. Each full PNG is **803 × 1110 pixels**;
integer pixel rounding introduces less than 0.03 mm of size difference.
The PDF uses exact **68 × 94 mm** pages and a centered **63 × 89 mm TrimBox**.
Print at actual size with automatic page fitting disabled.

```yaml
card:
  size_mm: [63, 89]
  dpi: 300
  bleed_mm: 2.5
  safe_margin_mm: 4
```

For exact pixel dimensions, replace `size_mm` with `size_px: [744, 1051]`;
use only one of these settings. For PNG-only builds, set `bleed_mm: 0` to
export without bleed. With `safe_margin_mm` configured, foreground placement
outside that inset is rejected before clipping, including decorative borders.
The default frame size is `[0.87, 0.87]` to keep the current deck inside 4 mm.

### Print PDF and shared back

```yaml
back: assets/BACK.png
pdf:
  icc_profile: assets/profiles/PSOcoated_v3.icc
```

The back is a complete transparent design: the builder centers its visible
bounds in the same frame-sized area as the fronts and adds the background,
without adding a frame or numbers. The `BACK.png` cleanup override preserves
the entire source before trimming transparent margins. Keep that override if
you rename or replace the back. Back placement can be adjusted with the
`frame` fields under `cards.BACK.png`. It does not increase the deck's card count.

The PDF contains the shared back followed by fronts in gallery order (special
cards, then families in numeric order). The current 59-card deck produces
60 pages, not 118. It embeds losslessly compressed CMYK images and a CMYK
output intent, with PDF/X-4 identification and metadata. There are no fonts,
interactive elements, or transparency in the PDF.

The default PSO Coated v3 / FOGRA51 profile is a coated-paper default, not a
printer-supplied press profile. Pillow/LittleCMS converts the rendered sRGB
pixels using relative colorimetric intent and black-point compensation.
Change `pdf.icc_profile` to use another CMYK output profile. PNGs and browser
previews stay RGB; CMYK conversion can change colours.

Geometry follows the shop's [card-specific technical sheet](https://www.jeudecartespersonnalise.fr/wp-content/uploads/2025/04/fiche-technique-jeu-de-carte.pdf):
exact full-bleed page size, explicit trim/bleed boxes, and no drawn cut outlines
or rounded-corner masks. We omit external crop marks to retain the requested
68 × 94 mm pages, despite the broader
[template page](https://www.jeudecartespersonnalise.fr/ressources/gabarits/)
recommending marks for professional software exports.

PDF export requires a back, an opaque background, at least 300 DPI, 2.5 mm
bleed, and at least 4 mm foreground clearance. Missing profiles, unsafe
placement, skipped fronts, empty decks, and PDFs over 500 MB fail the build.
The last successful PDF is replaced only after the new PDF passes structural
checks. These checks are not an independent PDF/X certification; the shop's
file review and proof remain the final print check.

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
artwork, frame, then numbers. With safety checking disabled in a PNG-only
configuration, anything outside the canvas is clipped.

### Crop and clean source images

`cleanup.crop` uses `[left, top, right, bottom]` as fractions of the source
image. The supplied `[0, 0, 1, 0.92]` keeps the top 92% to remove the watermark
on these exports. Adjust it for artwork with different margins.
Use `cleanup.assets` with an exact filename to override its crop or `trim`.
The supplied background and back keep their full source images.

To inspect cleanup and extracted digits without rendering the deck:

```sh
uv run magichien-builder --config config.yaml --process-only
```

Look in `assets/processed/cleaned/` and `assets/processed/digits/`.
A full build also saves each card's separate layers in
`assets/processed/layers/`. These intermediate files are ignored by Git.

If a number sheet can't be split into ten digits, PNG-only builds skip affected
cards with a warning; PDF builds fail rather than export an incomplete deck.
Overlapping shadows may leave fragments on neighboring
numbers. Space the source digits farther apart, or set
`digits.split_boundaries.NUMBERS_GREEN.png` to nine increasing x coordinates
measured in the **cleaned** sheet. `digits.detection_alpha` controls boundary
detection without changing the glyphs' transparency.

## Publish changes

Push or merge changes to `main` to rebuild and publish the
[live gallery](https://mortrevere.github.io/magichien-builder/).
The workflow commits the generated cards and galleries in `preview/` back to
`main`, makes the archive and PDF available to download, and deploys the site to
GitHub Pages. You can follow progress or start a build manually in
[Actions](https://github.com/mortrevere/magichien-builder/actions).
Tests run on pull requests only.

Both workflows download the colour profile during setup. Generated PDFs and
archives are ignored by Git and included in the deployment and build artifacts.

For a fork, select **Settings → Pages → Source → GitHub Actions** once.
Repository rules must allow the workflow to push generated files to `main`.
No custom secrets are needed.

Local builds replace matching outputs but leave old files in place. The
publishing workflow rebuilds `preview/` from scratch, so removed cards also
disappear from the published site. Keep `paths.rendered` and the workflow's
`preview/` paths in sync if you change the output directory.

## Development

The builder uses Pillow, PyYAML, and pypdf. After the profile setup above,
run the test suite with:

```sh
uv run python -m unittest discover -s tests
```
