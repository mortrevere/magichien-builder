"""One face per page, colour-managed PDF/X-4 for the card printer."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from PIL import Image, ImageCms
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject, NameObject,
    NumberObject, RectangleObject, TextStringObject,
)

from .config import dimensions, number, pair


MAX_PDF_BYTES = 500_000_000
MM_TO_PT = 72 / 25.4


def page_sizes(card):
    _, _, _, dpi = dimensions(card)
    trim = (pair(card["size_mm"], "size_mm", True) if "size_mm" in card else
            tuple(v * 25.4 / dpi for v in card["size_px"]))
    bleed = card.get("bleed_mm", 3)
    return trim, tuple(v + 2 * bleed for v in trim)


def prepare_pdf(config):
    """Validate print settings and build one reusable LittleCMS transform."""
    card = config["card"]
    _, _, _, dpi = dimensions(card)
    margin = number(card.get("safe_margin_mm", 4), "safe_margin_mm", positive=True)
    trim, _ = page_sizes(card)
    if dpi < 300 or card.get("bleed_mm", 3) != 2.5 or margin < 4:
        raise ValueError("PDF requires at least 300 DPI, 2.5 mm bleed and at least 4 mm safe margin")
    if min(trim) <= 2 * margin:
        raise ValueError("Card is too small for the PDF safe margin")
    profile_path = config["pdf"].get("icc_profile")
    try:
        profile = ImageCms.getOpenProfile(str(profile_path))
        if profile.profile.xcolor_space.strip() != "CMYK" or profile.profile.device_class != "prtr":
            raise ValueError("PDF ICC profile must be a CMYK output profile")
        transform = ImageCms.buildTransform(
            ImageCms.createProfile("sRGB"), profile, "RGB", "CMYK",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        )
    except (ImageCms.PyCMSError, OSError) as error:
        raise ValueError(f"Cannot load PDF ICC profile {profile_path}: {error}") from error
    return profile, transform


def safe_area(card):
    _, full, _, _ = dimensions(card)
    _, full_mm = page_sizes(card)
    margin = number(card.get("safe_margin_mm", 4), "safe_margin_mm", positive=True)
    inset = card.get("bleed_mm", 3) + margin
    x, y = (inset * px / mm for px, mm in zip(full, full_mm))
    return x, y, full[0] - x, full[1] - y


def check_safe_margin(stem, layers, card):
    left, top, right, bottom = safe_area(card)
    for name, layer in layers.items():
        if name == "01-background":
            continue
        bounds = layer.getchannel("A").getbbox()
        if bounds and (bounds[0] < left or bounds[1] < top or bounds[2] > right or bounds[3] > bottom):
            raise ValueError(f"{stem}: {name} enters the {card.get('safe_margin_mm', 4):g} mm safety margin")


def write_pdf(images, target, card, settings):
    """Embed lossless CMYK pixels, then validate and atomically publish the PDF."""
    if len(images) < 2:
        raise ValueError("PDF requires a shared back and at least one card front")
    profile, transform = settings
    trim_mm, full_mm = page_sizes(card)
    width, height = (v * MM_TO_PT for v in full_mm)
    bleed = card["bleed_mm"] * MM_TO_PT
    trim_box = [bleed, bleed, bleed + trim_mm[0] * MM_TO_PT, bleed + trim_mm[1] * MM_TO_PT]
    expected_size = dimensions(card)[1]
    writer = PdfWriter()
    writer.pdf_header = "%PDF-1.6"
    icc = DecodedStreamObject()
    icc.set_data(profile.tobytes())
    icc.update({NameObject("/N"): NumberObject(4)})
    icc_ref = writer._add_object(icc.flate_encode())
    intent = DictionaryObject({
        NameObject("/Type"): NameObject("/OutputIntent"),
        NameObject("/S"): NameObject("/GTS_PDFX"),
        NameObject("/OutputConditionIdentifier"): TextStringObject(ImageCms.getProfileDescription(profile).strip()),
        NameObject("/Info"): TextStringObject(ImageCms.getProfileInfo(profile).strip()),
        NameObject("/DestOutputProfile"): icc_ref,
    })
    writer.root_object[NameObject("/OutputIntents")] = ArrayObject([writer._add_object(intent)])
    for path in images:
        with Image.open(path) as source:
            if source.size != expected_size:
                raise ValueError(f"{path.name}: unexpected dimensions for PDF export")
            if source.mode == "RGBA" and source.getchannel("A").getextrema() != (255, 255):
                raise ValueError(f"{path.name}: PDF requires an opaque background")
            cmyk = ImageCms.applyTransform(source.convert("RGB"), transform)
        image = DecodedStreamObject()
        image.set_data(cmyk.tobytes())
        image.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(cmyk.width),
            NameObject("/Height"): NumberObject(cmyk.height),
            NameObject("/ColorSpace"): NameObject("/DeviceCMYK"),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/Intent"): NameObject("/RelativeColorimetric"),
        })
        page = writer.add_blank_page(width, height)
        page.trimbox = RectangleObject(trim_box)
        page.bleedbox = RectangleObject([0, 0, width, height])
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Card"): writer._add_object(image.flate_encode())}),
        })
        content = DecodedStreamObject()
        content.set_data(f"q {width:.8f} 0 0 {height:.8f} 0 0 cm /Card Do Q\n".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)

    now = datetime.now(timezone.utc)
    date = now.isoformat(timespec="seconds")
    pdf_date = now.strftime("D:%Y%m%d%H%M%SZ")
    document_id = f"uuid:{uuid4()}"
    writer.add_metadata({
        "/Title": "Magichien — print deck", "/Creator": "Magichien Builder", "/Producer": "Magichien Builder / pypdf",
        "/CreationDate": pdf_date, "/ModDate": pdf_date, "/GTS_PDFXVersion": "PDF/X-4",
    })
    writer._info[NameObject("/Trapped")] = NameObject("/False")
    writer.xmp_metadata = f'''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about=""
 xmlns:pdfxid="http://www.npes.org/pdfx/ns/id/"
 xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
 xmlns:xmp="http://ns.adobe.com/xap/1.0/"
 xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<pdfxid:GTS_PDFXVersion>PDF/X-4</pdfxid:GTS_PDFXVersion>
<pdf:Producer>Magichien Builder / pypdf</pdf:Producer><pdf:Trapped>False</pdf:Trapped>
<xmp:CreatorTool>Magichien Builder</xmp:CreatorTool>
<xmp:CreateDate>{date}</xmp:CreateDate><xmp:ModifyDate>{date}</xmp:ModifyDate>
<xmp:MetadataDate>{date}</xmp:MetadataDate>
<xmpMM:DocumentID>{document_id}</xmpMM:DocumentID><xmpMM:InstanceID>{document_id}</xmpMM:InstanceID>
<dc:format>application/pdf</dc:format>
<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Magichien — print deck</rdf:li></rdf:Alt></dc:title>
</rdf:Description></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>'''.encode("utf-8")
    writer.root_object["/Metadata"].update({NameObject("/Type"): NameObject("/Metadata"),
                                           NameObject("/Subtype"): NameObject("/XML")})
    writer.generate_file_identifiers()
    target = Path(target)
    with NamedTemporaryFile(dir=target.parent, prefix=".print-", suffix=".pdf", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        writer.write(temporary)
        if temporary.stat().st_size > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds the printer's 500 MB upload limit")
        with PdfReader(temporary, strict=True) as reader:
            if len(reader.pages) != len(images) or reader.is_encrypted:
                raise ValueError("PDF validation failed: incorrect page count or encryption")
            if reader.trailer["/Root"]["/OutputIntents"][0]["/DestOutputProfile"].get_data() != profile.tobytes():
                raise ValueError("PDF validation failed: incorrect output profile")
            for page in reader.pages:
                for actual, expected in ((page.mediabox, [0, 0, width, height]),
                                         (page.bleedbox, [0, 0, width, height]), (page.trimbox, trim_box)):
                    if any(abs(float(a) - b) > 0.00001 for a, b in zip(actual, expected)):
                        raise ValueError("PDF validation failed: incorrect page boxes")
                image = page["/Resources"]["/XObject"]["/Card"]
                if image["/ColorSpace"] != "/DeviceCMYK" or image["/Filter"] != "/FlateDecode":
                    raise ValueError("PDF validation failed: expected lossless CMYK images")
        # NamedTemporaryFile starts at 0600; the exported download must be readable by a web server.
        temporary.chmod(0o644)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
