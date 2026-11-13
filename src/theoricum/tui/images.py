"""Question images: decoding, quality tweaks and a small LRU cache.

textual-image re-encodes its image on every render, so it is fed in-memory PIL images that are
decoded once. Most question images are small (the magazine publishes 250×226 px, the Anki deck
~200 px), so they are always enlarged. Two tweaks make that look as sharp as possible on every
protocol (kitty TGP, Sixel in foot or Windows Terminal, color blocks):

- small images get a mild unsharp mask once, at their own size, and every resize uses Lanczos
  instead of textual-image's default bicubic filter;
- Sixel output (256 colors) is dithered (Floyd–Steinberg) instead of posterized.

Both hook into textual-image internals (`PixelData.scaled`, `_sixel._quantize_rgb_image`). If a
future version renames them, `install_quality_hooks` leaves the library untouched (images still
work, just softer) and the tests flag it.
"""

import logging
from collections import OrderedDict
from io import BytesIO

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError
from textual.widget import Widget

from theoricum.media import MediaError, MediaResolver

logger = logging.getLogger(__name__)

MAX_SIDE = 1600  # enough for a full-screen zoom; larger sources are reduced once
PIXEL_BUDGET = 24_000_000  # decoded pixels kept in memory (~72 MB in RGB)
SHARPEN_BELOW = 640  # images smaller than this (longest side) are always enlarged
SHARPEN = ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=1)


def sharpen(image: Image.Image) -> Image.Image:
    """Mild unsharp mask on the color bands (sharpening alpha would fringe the edges)."""
    if image.mode == "RGBA":
        rgb = image.convert("RGB").filter(SHARPEN)
        rgb.putalpha(image.getchannel("A"))
        return rgb
    return image.filter(SHARPEN)


def prepare(data: bytes) -> Image.Image:
    """Decode an image file: upright, RGB(A), at most MAX_SIDE, small ones pre-sharpened."""
    image = Image.open(BytesIO(data))
    image.load()
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "RGBA"):
        transparent = image.mode in ("LA", "PA") or "transparency" in image.info
        image = image.convert("RGBA" if transparent else "RGB")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS, reducing_gap=3.0)
    elif max(image.size) < SHARPEN_BELOW:
        image = sharpen(image)
    return image


class ImageCache:
    def __init__(
        self, media: MediaResolver, *, max_items: int = 60, pixel_budget: int = PIXEL_BUDGET
    ) -> None:
        self.media = media
        self.max_items = max_items
        self.pixel_budget = pixel_budget
        self._items: OrderedDict[str, Image.Image | None] = OrderedDict()

    def get(self, ref: str) -> Image.Image | None:
        """The decoded image, or None if it cannot be read (the failure is cached too)."""
        if ref in self._items:
            self._items.move_to_end(ref)
            return self._items[ref]
        image = self._load(ref)
        self._items[ref] = image
        while len(self._items) > 1 and (
            len(self._items) > self.max_items or self._pixels() > self.pixel_budget
        ):
            self._items.popitem(last=False)
        return image

    def _pixels(self) -> int:
        return sum(i.width * i.height for i in self._items.values() if i is not None)

    def _load(self, ref: str) -> Image.Image | None:
        try:
            return prepare(self.media.read(ref))
        except OSError, MediaError, UnidentifiedImageError, ValueError, EOFError:
            return None


# --- textual-image quality hooks ---------------------------------------------------------------


def _lanczos_scaled(self, width: int, height: int):
    """Replacement for `PixelData.scaled`: Lanczos (with a reducing gap when shrinking)."""
    from textual_image._pixeldata import PixelData

    size = (max(1, width), max(1, height))
    image = self.pil_image
    if image.size == size:
        return PixelData(image)
    if image.mode not in ("RGB", "RGBA", "L", "LA"):  # palette images would fall back to NEAREST
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    return PixelData(image.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0))


def _dithered_quantize(image: Image.Image, options) -> Image.Image:
    """Replacement for `_sixel._quantize_rgb_image`: same palette, Floyd–Steinberg dithering."""
    from textual_image import _sixel

    method = _sixel._QUANTIZE_METHODS.get(options.quantize, Image.Quantize.FASTOCTREE)
    palette = image.quantize(colors=options.colors, method=method)
    return image.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)


def install_quality_hooks() -> bool:
    """Patch textual-image (idempotent). Returns whether both hooks are in place."""
    try:
        from textual_image import _pixeldata, _sixel
    except ImportError:
        return False
    installed = True
    if callable(getattr(_pixeldata.PixelData, "scaled", None)):
        _pixeldata.PixelData.scaled = _lanczos_scaled  # type: ignore[method-assign]
    else:
        installed = False
    if callable(getattr(_sixel, "_quantize_rgb_image", None)) and hasattr(
        _sixel, "_QUANTIZE_METHODS"
    ):
        _sixel._quantize_rgb_image = _dithered_quantize
    else:
        installed = False
    if not installed:
        logger.warning("textual-image changed: image quality hooks not installed")
    return installed


# --- diagnostics -------------------------------------------------------------------------------

PROTOCOL_LABELS = {
    "tgp": "protocolo gráfico de kitty (TGP)",
    "sixel": "Sixel",
    "halfcell": "bloques de color (la terminal no admite gráficos)",
    "unicode": "caracteres Unicode (la terminal no admite gráficos)",
}


def protocol_of(image_cls: type[Widget]) -> str:
    """tgp | sixel | halfcell | unicode, for the widget class the app uses."""
    from textual_image.widget import SixelImage

    if issubclass(image_cls, SixelImage):
        return "sixel"
    renderable = getattr(image_cls, "_Renderable", None)
    module = getattr(renderable, "__module__", "")
    return module.rsplit(".", 1)[-1] if module else "unicode"


def describe_images(image_cls: type[Widget]) -> str:
    """One line for the help screens: how images are drawn, and how to get more detail."""
    from textual_image._terminal import get_cell_size

    protocol = protocol_of(image_cls)
    cell = get_cell_size()
    line = f"Imágenes: {PROTOCOL_LABELS.get(protocol, protocol)}"
    if protocol in ("tgp", "sixel"):
        line += f", celdas de {cell.width}×{cell.height} px"
    line += ". Pulsa z para verlas a pantalla completa."
    if protocol in ("halfcell", "unicode"):
        line += (
            "\nPara verlas nítidas usa kitty, foot, WezTerm o Windows Terminal 1.22+ "
            "(o fuerza el método con --image-protocol)."
        )
    return line
