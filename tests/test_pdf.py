from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image, ImageCms, ImageOps
from pypdf import PdfReader

from magichien_builder.assets import AssetCleaner
from magichien_builder.config import dimensions, load_config
from magichien_builder.main import build, render_card
from magichien_builder.pdf import MM_TO_PT, check_safe_margin, prepare_pdf, write_pdf


ROOT = Path(__file__).resolve().parents[1]


class PrintTests(unittest.TestCase):
    def test_pdf_geometry_colour_metadata_and_lossless_pixels(self):
        config = load_config(ROOT / "config.yaml")
        settings = prepare_pdf(config)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            images = []
            # Asymmetric content catches channel inversions and lossy compression.
            for name, colour in (("BACK", "red"), ("CARD_NN1", "blue")):
                path = directory / f"{name}.png"
                image = Image.new("RGBA", dimensions(config["card"])[1], colour)
                image.putpixel((0, 0), (12, 123, 234, 255))
                image.save(path, dpi=(300, 300))
                images.append(path)
            target = directory / "deck.pdf"
            write_pdf(images, target, config["card"], settings)
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            with PdfReader(target, strict=True) as pdf:
                self.assertEqual(len(pdf.pages), 2)
                self.assertEqual(pdf.pdf_header, "%PDF-1.6")
                self.assertFalse(pdf.is_encrypted)
                self.assertEqual(pdf.metadata["/GTS_PDFXVersion"], "PDF/X-4")
                self.assertEqual(pdf.metadata["/Trapped"], "/False")
                root = pdf.trailer["/Root"]
                self.assertEqual(len(pdf.trailer["/ID"]), 2)
                intent = root["/OutputIntents"][0].get_object()
                self.assertEqual(intent["/S"], "/GTS_PDFX")
                self.assertEqual(intent["/DestOutputProfile"]["/N"], 4)
                self.assertEqual(intent["/DestOutputProfile"].get_data(), settings[0].tobytes())
                metadata = root["/Metadata"]
                self.assertEqual(metadata["/Subtype"], "/XML")
                xmp = ET.fromstring(metadata.get_data())
                self.assertEqual(xmp.find('.//{http://www.npes.org/pdfx/ns/id/}GTS_PDFXVersion').text, 'PDF/X-4')
                self.assertEqual(xmp.find('.//{http://ns.adobe.com/pdf/1.3/}Producer').text, pdf.metadata.producer)
                for page, path in zip(pdf.pages, images):
                    for box, expected in ((page.mediabox, [0, 0, 68, 94]),
                                          (page.bleedbox, [0, 0, 68, 94]),
                                          (page.trimbox, [2.5, 2.5, 65.5, 91.5])):
                        for actual, mm in zip(box, expected):
                            self.assertAlmostEqual(float(actual) / MM_TO_PT, mm, places=6)
                    self.assertNotIn("/ArtBox", page)
                    xobjects = page["/Resources"]["/XObject"]
                    self.assertEqual(len(xobjects), 1)
                    image = xobjects["/Card"]
                    self.assertEqual(image["/ColorSpace"], "/DeviceCMYK")
                    self.assertEqual(image["/Filter"], "/FlateDecode")
                    self.assertEqual(image["/BitsPerComponent"], 8)
                    self.assertEqual((image["/Width"], image["/Height"]), (803, 1110))
                    self.assertNotIn("/SMask", image)
                    with Image.open(path) as source:
                        expected = ImageCms.applyTransform(source.convert("RGB"), settings[1])
                    self.assertEqual(image.get_data(), expected.tobytes())
            # A failed export must preserve the last successful PDF and clean up its temporary file.
            original = target.read_bytes()
            with patch("magichien_builder.pdf.MAX_PDF_BYTES", 1):
                with self.assertRaisesRegex(ValueError, "500 MB"):
                    write_pdf(images, target, config["card"], settings)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(directory.glob('.print-*')), [])
            with self.assertRaisesRegex(ValueError, "at least one card"):
                write_pdf(images[:1], target, config["card"], settings)
            Image.new("RGBA", (803, 1110)).save(images[0])
            with self.assertRaisesRegex(ValueError, "opaque background"):
                write_pdf(images, target, config["card"], settings)
            self.assertEqual(target.read_bytes(), original)

    def test_complete_back_and_foreground_safety(self):
        config = load_config(ROOT / "config.yaml")
        cleaner = AssetCleaner(config["cleanup"])
        with Image.open(config["back"]) as original:
            back = cleaner.clean(original, "BACK.png")
            # BACK has artwork in the bottom 8% that the normal cleanup would cut off.
            expected = original.crop(original.getchannel("A").getbbox())
            self.assertEqual(back.size, (691, 921))
            self.assertEqual(back.tobytes(), expected.tobytes())
        with Image.open(config["background"]) as original:
            background = cleaner.clean(original, "background.png")
        empty = Image.new("RGBA", (1, 1))
        result, layers, _ = render_card(empty, back, {}, None, background, config["card"], config["layout"])
        check_safe_margin("BACK", layers, config["card"])
        self.assertEqual(result.size, (803, 1110))
        self.assertEqual(result.getchannel("A").getextrema(), (255, 255))
        expected_background = ImageOps.fit(background, result.size, method=Image.Resampling.LANCZOS)
        for point in ((0, 0), (802, 0), (0, 1109), (802, 1109)):
            self.assertEqual(result.getpixel(point), expected_background.getpixel(point))
        for center in ((.1, .5), (10, 10)):
            layout = deepcopy(config["layout"])
            layout["frame"]["center"] = center
            with self.assertRaisesRegex(ValueError, "safety margin"):
                render_card(empty, back, {}, None, background, config["card"], layout)
        layers["03-frame"].putpixel((0, 0), (0, 0, 0, 1))
        with self.assertRaisesRegex(ValueError, "BACK.*safety margin"):
            check_safe_margin("BACK", layers, config["card"])

    def test_invalid_profile_and_print_settings(self):
        config = load_config(ROOT / "config.yaml")
        for field, value in (("dpi", 72), ("bleed_mm", 3), ("safe_margin_mm", 3)):
            invalid = deepcopy(config)
            invalid["card"][field] = value
            with self.assertRaisesRegex(ValueError, "PDF requires"):
                prepare_pdf(invalid)
        config["pdf"]["icc_profile"] = ROOT / "does-not-exist.icc"
        with self.assertRaisesRegex(ValueError, "Cannot load PDF ICC profile"):
            prepare_pdf(config)
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = Path(temporary) / "rgb.icc"
            profile_path.write_bytes(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
            config["pdf"]["icc_profile"] = profile_path
            with self.assertRaisesRegex(ValueError, "CMYK output profile"):
                prepare_pdf(config)

    def test_pdf_build_rejects_missing_back_skipped_fronts_and_unsafe_card(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            assets.mkdir()
            config = load_config(ROOT / "config.yaml")
            config["paths"] = {"assets": assets, "processed": root / "processed", "rendered": root / "rendered"}
            config["background"] = assets / "background.png"
            config["back"] = assets / "BACK.png"
            for name in ("background.png", "FRAME_GREEN.png", "GREEN_5.png"):
                shutil.copy2(ROOT / "assets" / name, assets / name)
            with self.assertRaisesRegex(ValueError, "Back must be a PNG"):
                build(config)
            shutil.copy2(ROOT / "assets/BACK.png", config["back"])
            with self.assertRaisesRegex(ValueError, "incomplete PDF.*GREEN_5"):
                build(config)
            self.assertFalse(config["paths"]["rendered"].exists())
            shutil.copy2(ROOT / "assets/NUMBERS_GREEN.png", assets / "NUMBERS_GREEN.png")
            config["cards"]["GREEN_5.png"] = {"subject": {"center": [10, 10]}}
            with self.assertRaisesRegex(ValueError, "GREEN_5.*safety margin"):
                build(config)
            self.assertFalse((config["paths"]["rendered"] / "rendered-cards.pdf").exists())


if __name__ == "__main__":
    unittest.main()
