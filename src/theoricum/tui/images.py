"""Decode question images once, downscale them and keep a small LRU cache.

textual-image re-encodes its image on every render, so it is fed small in-memory PIL images.
"""

from collections import OrderedDict
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from theoricum.media import MediaError, MediaResolver


class ImageCache:
    def __init__(self, media: MediaResolver, *, max_items: int = 40, max_side: int = 900) -> None:
        self.media = media
        self.max_items = max_items
        self.max_side = max_side
        self._items: OrderedDict[str, Image.Image | None] = OrderedDict()

    def get(self, ref: str) -> Image.Image | None:
        """The decoded image, or None if it cannot be read (the failure is cached too)."""
        if ref in self._items:
            self._items.move_to_end(ref)
            return self._items[ref]
        image = self._load(ref)
        self._items[ref] = image
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return image

    def _load(self, ref: str) -> Image.Image | None:
        try:
            image = Image.open(BytesIO(self.media.read(ref)))
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if image.mode in ("LA", "P", "PA") else "RGB")
            image.thumbnail((self.max_side, self.max_side))
            return image
        except OSError, MediaError, UnidentifiedImageError, ValueError, EOFError:
            return None
