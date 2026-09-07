from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

from PIL import Image, ImageChops

from magichien_builder.assets import AssetCleaner, discover_cards, split_digits
from magichien_builder.config import dimensions, layout_for, load_config
from magichien_builder.main import build, number_image, render_card, write_catalog


ROOT = Path(__file__).resolve().parents[1]


class BuilderTests(unittest.TestCase):
    def test_catalog_order_and_relative_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cards = [("GREEN_10", "GREEN", "10"), ("WOAF_NN1", "WOAF", None),
                     ("GREEN_2", "GREEN", "2"), ("MAGE_NN1", "MAGE", None),
                     ("BLUE_1", "BLUE", "1"), ("SPACE FAMILY_1", "SPACE FAMILY", "1")]
            write_catalog(cards, directory)
            catalog = (directory / "CARDS.md").read_text()
            order = ["MAGE_NN1", "WOAF_NN1", "BLUE_1", "GREEN_2", "GREEN_10", "SPACE FAMILY_1"]
            self.assertEqual(sorted(order, key=catalog.index), order)
            self.assertIn("6 rendered cards", catalog)
            self.assertIn('src="SPACE%20FAMILY_1.png"', catalog)
            page = (directory / "index.html").read_text()
            self.assertEqual(sorted(order, key=page.index), order)
            self.assertIn('src="previews/SPACE%20FAMILY_1.webp"', page)
            self.assertIn('href="rendered-cards.tar.gz"', page)
            write_catalog([], directory)
            self.assertIn("0 rendered cards", (directory / "CARDS.md").read_text())
            self.assertNotIn("GREEN_2", (directory / "CARDS.md").read_text())

    def test_dimensions_and_invalid_settings(self):
        trim, full, offset, dpi = dimensions({"size_mm": [63, 89], "dpi": 300, "bleed_mm": 3})
        self.assertEqual((trim, full, offset, dpi), ((744, 1051), (815, 1122), (35, 35), 300))
        self.assertEqual(dimensions({"size_px": [100, 200], "bleed_mm": 0})[:2], ((100, 200), (100, 200)))
        for card in ({}, {"size_px": [1, 2], "size_mm": [1, 2]},
                     {"size_px": [1.5, 2]}, {"size_mm": [0, 2]},
                     {"size_px": [10, 20], "bleed_mm": -1}):
            with self.assertRaises(ValueError):
                dimensions(card)

    def test_cleanup_preserves_pixels_and_original(self):
        source = Image.new("RGBA", (100, 100))
        source.paste((20, 40, 60, 97), (10, 10, 20, 20))
        source.paste((255, 255, 255, 255), (90, 95, 100, 100))
        before = source.tobytes()
        cleaner = AssetCleaner({"crop": [0, 0, 1, .92], "assets": {
            "background.png": {"crop": [0, 0, 1, 1], "trim": False}}})
        result = cleaner.clean(source, "subject.png")
        self.assertEqual(result.size, (10, 10))
        self.assertEqual(result.getpixel((0, 0)), (20, 40, 60, 97))
        self.assertEqual(source.tobytes(), before)
        self.assertEqual(cleaner.clean(source, "background.png").size, (100, 100))

    def test_naming(self):
        paths = [Path(name) for name in ["GREEN_5.png", "FRAME_GREEN.png", "NUMBERS_GREEN.png",
                 "WOAF_NN1.png", "LONG_FAMILY_12.png", "carte type example.png", "background.png"]]
        self.assertEqual(discover_cards(paths), [("GREEN_5", "GREEN", "5"),
                         ("LONG_FAMILY_12", "LONG_FAMILY", "12"), ("WOAF_NN1", "WOAF", None)])

    def test_glyph_splitting_and_spacing(self):
        sheet = Image.new("RGBA", (100, 20))
        for i in range(10):
            sheet.paste((i * 20, 30, 40, 100), (i * 10 + 2, 3, i * 10 + 7, 18))
        digits = split_digits(sheet)
        self.assertEqual(len(digits), 10)
        self.assertEqual(digits["5"].size, (5, 20))
        self.assertEqual(digits["5"].getpixel((2, 5)), (80, 30, 40, 100))
        self.assertEqual(number_image("12", digits, 20, .2).size, (18, 20))
        with self.assertRaisesRegex(ValueError, "missing glyphs: 0"):
            number_image("10", {k: v for k, v in digits.items() if k != "0"}, 20, 0)
        with self.assertRaisesRegex(ValueError, "expected 10"):
            split_digits(Image.new("RGBA", (10, 10)))
        with self.assertRaisesRegex(ValueError, "Found 9 digits, expected 10"):
            split_digits(sheet.crop((0, 0, 90, 20)))
        with self.assertRaises(ValueError):
            split_digits(sheet, boundaries=[0] * 8)
        with self.assertRaises(ValueError):
            split_digits(sheet, boundaries=[0] * 9)

    def test_overrides(self):
        config = {"layout": {"subject": {"scale": 1, "center": [.5, .5]}},
                  "families": {"GREEN": {"subject": {"scale": .8}}},
                  "cards": {"GREEN_5.png": {"subject": {"scale": .7, "center": [.3, .4]}}}}
        self.assertEqual(layout_for(config, "GREEN", "GREEN_5.png")["subject"],
                         {"scale": .7, "center": [.3, .4]})
        self.assertEqual(layout_for(config, "GREEN", "GREEN_6.png")["subject"]["scale"], .8)
        self.assertEqual(config["layout"]["subject"]["scale"], 1)

    def test_ten_digit_sheet_maps_last_glyph_to_zero(self):
        sheet = Image.new("RGBA", (100, 20))
        for i in range(10):
            sheet.paste((i * 20, 30, 40, 100), (i * 10 + 2, 3, i * 10 + 7, 18))
        for boundaries in (None, list(range(10, 100, 10))):
            with self.subTest(boundaries=boundaries):
                digits = split_digits(sheet, boundaries=boundaries)
                self.assertEqual(list(digits), list("1234567890"))
                self.assertEqual(digits["0"].getpixel((2, 5)), (180, 30, 40, 100))
                value = number_image("10", digits, 20, .2)
                self.assertEqual(value.size, (18, 20))
                # Resampling translucent pixels can round a color channel by one.
                for actual, expected in zip(value.getpixel((14, 5)), (180, 30, 40, 100)):
                    self.assertAlmostEqual(actual, expected, delta=1)

    def test_number_alignment_and_corner_width(self):
        one = Image.new("RGBA", (10, 30))
        zero = Image.new("RGBA", (20, 30))
        one.paste("red", (0, 8, 10, 28))
        zero.paste("blue", (0, 0, 20, 18))
        label = number_image("10", {"1": one, "0": zero}, 40, .1)
        for channel in ("R", "B"):
            bounds = label.getchannel(channel).getbbox()
            self.assertEqual((bounds[1], bounds[3]), (0, 40))
        layout = {"frame": {"size": [1, 1], "center": [.5, .5]},
                  "subject": {"size": [.5, .5], "center": [.5, .5]},
                  "numbers": {"height": .2, "max_width": .18, "placements": [
                      {"center": [.2, .2], "rotation": 0},
                      {"center": [.8, .8], "rotation": 180}]}}
        transparent = Image.new("RGBA", (200, 200))
        _, layers, _ = render_card(transparent, transparent, {"1": one, "0": zero},
                                   "10", None, {"size_px": [200, 200], "bleed_mm": 0}, layout)
        for box in ((0, 0, 100, 100), (100, 100, 200, 200)):
            bounds = layers["04-numbers"].crop(box).getbbox()
            self.assertLessEqual(bounds[2] - bounds[0], 36)

    def test_rotation_no_number_and_bleed(self):
        glyph = Image.new("RGBA", (10, 20))
        glyph.paste("red", (0, 0, 5, 10))
        glyph.putpixel((9, 19), (0, 0, 255, 255))
        layout = {"frame": {"size": [.5, .5], "center": [.5, .5]},
                  "subject": {"size": [.5, .5], "center": [.5, .5]},
                  "numbers": {"height": .4, "placements": [
                      {"center": [.25, .25], "rotation": 0},
                      {"center": [.75, .75], "rotation": 180}]}}
        transparent = Image.new("RGBA", (100, 100))
        args = (transparent, transparent, {"1": glyph}, "1", Image.new("RGBA", (10, 10), "white"),
                {"size_px": [200, 200], "bleed_mm": 0}, layout)
        result, layers, _ = render_card(*args)
        alpha = layers["04-numbers"].getchannel("A")
        self.assertEqual(alpha.getpixel((66, 56)), 255)
        self.assertEqual(alpha.getpixel((126, 136)), 255)
        self.assertEqual(alpha.getpixel((66, 86)), 0)
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255, 255))
        _, layers, _ = render_card(transparent, transparent, {}, None, None, args[5], layout)
        self.assertIsNone(layers["04-numbers"].getbbox())

    def test_two_digit_labels_clear_supplied_frames(self):
        config = load_config(ROOT / "config.yaml")
        cleaner = AssetCleaner(config["cleanup"])
        transparent = Image.new("RGBA", (1, 1))
        for family in ("BLUE", "GREEN", "RED"):
            assets = {}
            for prefix in ("FRAME", "NUMBERS"):
                filename = f"{prefix}_{family}.png"
                with Image.open(ROOT / "assets" / filename) as source:
                    assets[prefix] = cleaner.clean(source, filename)
            digits = split_digits(assets["NUMBERS"])
            for value in ("10", "11", "12", "13"):
                with self.subTest(family=family, value=value):
                    _, layers, _ = render_card(transparent, assets["FRAME"], digits, value,
                                               None, config["card"],
                                               layout_for(config, family, f"{family}_{value}.png"))
                    frame, numbers = [layers[key].getchannel("A").point(lambda a: 255 if a > 32 else 0)
                                      for key in ("03-frame", "04-numbers")]
                    self.assertIsNone(ImageChops.multiply(frame, numbers).getbbox())

    def test_supplied_assets_end_to_end(self):
        config = load_config(ROOT / "config.yaml")
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary) / "assets"
            assets.mkdir()
            # Fix the input set so adding new deck assets cannot race this test.
            for filename in ("GREEN_5.png", "WOAF_NN1.png", "FRAME_GREEN.png", "FRAME_WOAF.png",
                             "NUMBERS_GREEN.png", "NUMBERS_BLUE.png", "NUMBERS_RED.png",
                             "NUMBERS_YELLOW.png", "background.png"):
                shutil.copy2(ROOT / "assets" / filename, assets / filename)
            config["paths"]["assets"] = assets
            config["background"] = assets / "background.png"
            config["paths"]["processed"] = Path(temporary) / "processed"
            config["paths"]["rendered"] = Path(temporary) / "rendered"
            outputs = build(config)
            self.assertEqual({"GREEN_5.png", "WOAF_NN1.png"}, {p.name for p in outputs})
            catalog = (config["paths"]["rendered"] / "CARDS.md").read_text()
            self.assertLess(catalog.index("WOAF_NN1"), catalog.index("GREEN_5"))
            with tarfile.open(config["paths"]["rendered"] / "rendered-cards.tar.gz") as archive:
                self.assertEqual(set(archive.getnames()), {
                    "GREEN_5.png", "WOAF_NN1.png", "previews/GREEN_5.webp",
                    "previews/WOAF_NN1.webp", "CARDS.md", "index.html"})
            with Image.open(config["paths"]["rendered"] / "previews/GREEN_5.webp") as preview:
                self.assertLessEqual(preview.width, 360)
                self.assertLessEqual(preview.height, 510)
            for sheet in config["paths"]["assets"].glob("NUMBERS_*.png"):
                glyphs = {p.stem for p in (config["paths"]["processed"] / "digits" / sheet.stem[8:]).glob("*.png")}
                self.assertEqual(glyphs, set("1234567890"))
            for output in outputs:
                with Image.open(output) as image:
                    self.assertEqual(image.size, (815, 1122))
                    self.assertAlmostEqual(image.info["dpi"][0], 300, delta=.02)
                    self.assertEqual(image.getchannel("A").getextrema(), (255, 255))
            with Image.open(config["paths"]["processed"] / "cleaned/FRAME_GREEN.png") as image:
                self.assertEqual(image.size, (1343, 1791))
            with Image.open(config["paths"]["processed"] / "cleaned/GREEN_5.png") as image:
                self.assertEqual(image.size, (860, 1548))
            with Image.open(config["paths"]["processed"] / "layers/WOAF_NN1/04-numbers.png") as image:
                self.assertIsNone(image.getbbox())

    def test_missing_frame_and_sheet(self):
        for name, expected in [("UNKNOWN_5.png", "missing FRAME_UNKNOWN"),
                               ("MAGE_5.png", "missing NUMBERS_MAGE")]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                assets = root / "assets"
                assets.mkdir()
                Image.new("RGBA", (10, 10), "red").save(assets / name)
                if name.startswith("MAGE"):
                    Image.new("RGBA", (10, 10), "red").save(assets / "FRAME_MAGE.png")
                config = load_config(ROOT / "config.yaml")
                config["paths"] = {"assets": assets, "processed": root / "processed", "rendered": root / "rendered"}
                config["background"] = None
                if name.startswith("UNKNOWN"):
                    with self.assertRaisesRegex(ValueError, expected):
                        build(config)
                else:
                    with self.assertLogs("magichien_builder.main", level="WARNING") as logs:
                        self.assertEqual(build(config), [])
                    self.assertIn("missing or unusable NUMBERS_MAGE", '\n'.join(logs.output))
                self.assertEqual(build(config, process_only=True), [])
                self.assertEqual(list(config["paths"]["rendered"].glob("*.png")), [])

    def test_unusable_or_missing_sheet_warn_and_skip(self):
        for invalid_sheet in (True, False):
            with self.subTest(invalid_sheet=invalid_sheet), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                assets = root / "assets"
                assets.mkdir()
                for name in ("GREEN_10.png", "GREEN_NN1.png", "FRAME_GREEN.png"):
                    Image.new("RGBA", (20, 20), "red").save(assets / name)
                sheet = Image.new("RGBA", (90, 20))
                for i in range(9):
                    sheet.paste((20, 30, 40, 100), (i * 10 + 2, 3, i * 10 + 7, 18))
                if invalid_sheet:
                    sheet.save(assets / "NUMBERS_GREEN.png")
                config = load_config(ROOT / "config.yaml")
                config["paths"] = {"assets": assets, "processed": root / "processed", "rendered": root / "rendered"}
                config["background"] = None
                with self.assertLogs("magichien_builder", level="WARNING") as logs:
                    outputs = build(config)
                self.assertEqual([p.name for p in outputs], ["GREEN_NN1.png"])
                catalog = (root / "rendered" / "CARDS.md").read_text()
                self.assertIn("GREEN_NN1", catalog)
                self.assertNotIn("GREEN_10", catalog)
                message = '\n'.join(logs.output)
                self.assertIn("Skipping GREEN_10", message)
                if invalid_sheet:
                    self.assertIn("own column, sufficiently spaced", message)
                else:
                    self.assertIn("missing or unusable NUMBERS_GREEN", message)

    def test_overlapping_shadows_warn_without_discarding_glyphs(self):
        sheet = Image.new("RGBA", (100, 20), (20, 30, 40, 10))
        for i in range(10):
            sheet.paste((20, 30, 40, 100), (i * 10 + 2, 3, i * 10 + 7, 18))
        with self.assertLogs("magichien_builder.assets", level="WARNING") as logs:
            digits = split_digits(sheet, filename="NUMBERS_TEST.png")
        self.assertEqual(len(digits), 10)
        self.assertIn("NUMBERS_TEST.png", logs.output[0])
        self.assertIn("own column, sufficiently spaced", logs.output[0])
        self.assertEqual(digits["5"].getchannel("A").getextrema()[1], 100)


if __name__ == "__main__":
    unittest.main()
