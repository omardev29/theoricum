"""Build a tiny PDF laid out like the sign catalogue of the BOE (RD 465/2025) for the tests.

Like the real one, every page draws its table inside a form XObject (text and JPEG images),
codes are split into chunks («P», «-», «1»), variant letters are set apart («R-308» + «d»), the
BOE header sits at the top and the «cve» note is rotated on the side.
"""

from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image


@dataclass
class Row:
    code: str  # e.g. "P-1" or "R-308d"
    name: list[str]  # one entry per line (names may wrap)
    meaning: list[str]
    color: tuple[int, int, int]  # the picture is a plain square of this color


@dataclass
class Page:
    heading: str
    rows: list[Row]
    before: list[str] = field(default_factory=list)  # meaning that continues from the last page


def jpeg(color: tuple[int, int, int]) -> bytes:
    out = BytesIO()
    Image.new("RGB", (60, 50), color).save(out, format="JPEG", quality=95)
    return out.getvalue()


def _text(x: float, y: float, value: str, size: float = 11, rotated: bool = False) -> str:
    escaped = value.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(")
    escaped = escaped.replace(b")", b"\\)").decode("latin-1")
    matrix = f"0 1 -1 0 {x} {y}" if rotated else f"1 0 0 1 {x} {y}"
    return f"BT /F1 {size} Tf {matrix} Tm ({escaped}) Tj ET\n"


def _code_chunks(code: str, y: float) -> str:
    letter, rest = code.split("-")
    digits = rest.rstrip("abcdefghijklmnopqrstuvwxyz")
    out = _text(198.8, y, letter) + _text(206.8, y, "-") + _text(210.8, y, digits)
    if variant := rest[len(digits) :]:
        out += _text(232.0, y, variant)  # far enough to fall in the name column
    return out


def _form_content(page: Page) -> tuple[str, list[bytes]]:
    out = _text(196.6, 708.6, page.heading)
    y = 690.0
    for line in page.before:
        out += _text(198.8, y, line)
        y -= 15
    images = []
    y -= 10
    for row in page.rows:
        top = y
        out += _code_chunks(row.code, y)
        for k, part in enumerate(row.name):
            out += _text(262.5, y - 14 * k, part)
        y -= 14 * len(row.name) + 16
        for part in row.meaning:
            out += _text(198.8, y, part)
            y -= 15
        bottom = y
        y -= 20
        box = 50.0
        middle = (top + 10 + bottom) / 2
        name = f"Im{len(images)}"
        out += f"q 60 0 0 {box} 105 {middle - box / 2} cm /{name} Do Q\n"
        images.append(jpeg(row.color))
    return out, images


def build_catalogue_pdf(pages: list[Page]) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def stream(header: str, data: bytes) -> bytes:
        return f"<< {header} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"

    catalog = add(b"")  # filled at the end
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kids = []
    for page in pages:
        content, images = _form_content(page)
        image_ids = [
            add(
                stream(
                    "/Type /XObject /Subtype /Image /Width 60 /Height 50 /ColorSpace /DeviceRGB "
                    "/BitsPerComponent 8 /Filter /DCTDecode",
                    data,
                )
            )
            for data in images
        ]
        xobjects = " ".join(f"/Im{k} {obj} 0 R" for k, obj in enumerate(image_ids))
        form = add(
            stream(
                "/Type /XObject /Subtype /Form /BBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font} 0 R >> /XObject << {xobjects} >> >>",
                content.encode("latin-1"),
            )
        )
        page_content = (
            _text(145, 785, "BOLETÍN OFICIAL DEL ESTADO", 14)
            + _text(28, 760, "Núm. 145 Martes 17 de junio de 2025 Sec. I. Pág. 1")
            + "q /I1 Do Q\n"
            + _text(570, 62, "cve: BOE-A-2025-12199", 8, rotated=True)
        )
        contents = add(stream("", page_content.encode("latin-1")))
        kids.append(
            add(
                f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font} 0 R >> /XObject << /I1 {form} 0 R >> >> "
                f"/Contents {contents} 0 R >>".encode()
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    refs = " ".join(f"{k} 0 R" for k in kids)
    objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{refs}] /Count {len(kids)} >>".encode()

    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n".encode())
    out.write(f"startxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def build_text_pdf(pages: list[list[str]], bookmarks: list[tuple[str, int]] = ()) -> bytes:
    """A PDF whose pages hold these lines of text, with top-level bookmarks (title, page index),
    like the DGT manual («Tema 01» → its first page)."""
    from pypdf import PdfReader, PdfWriter

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kids = []
    for lines in pages:
        content = "".join(_text(72, 760 - 18 * k, line) for k, line in enumerate(lines))
        data = content.encode("latin-1")
        stream = add(f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")
        kids.append(
            add(
                f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {stream} 0 R >>".encode()
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    refs = " ".join(f"{k} 0 R" for k in kids)
    objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{refs}] /Count {len(kids)} >>".encode()
    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n".encode())
    out.write(f"startxref\n{xref}\n%%EOF\n".encode())

    writer = PdfWriter(clone_from=PdfReader(BytesIO(out.getvalue())))
    for title, index in bookmarks:
        writer.add_outline_item(title, index)
    final = BytesIO()
    writer.write(final)
    return final.getvalue()
