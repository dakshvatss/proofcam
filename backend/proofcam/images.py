"""Image acquisition and normalization.

Every image is normalized ONCE (EXIF orientation applied, RGB, long side capped) and the
same bytes are sent to Muse and SAM. All coordinates in ProofCam refer to this normalized
image; overlays are drawn on it, never on the original or the live preview.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageLoadError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedImage:
    image_id: str
    source_name: str
    width: int
    height: int
    jpeg_bytes: bytes
    original_size: tuple[int, int]

    def data_url(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.jpeg_bytes).decode("ascii")

    def pil(self) -> Image.Image:
        return Image.open(io.BytesIO(self.jpeg_bytes)).convert("RGB")


def normalize_image_bytes(data: bytes, source_name: str, max_side: int = 1600) -> NormalizedImage:
    if not data:
        raise ImageLoadError(f"{source_name}: empty file")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ImageLoadError(f"{source_name}: not a decodable image ({e})") from e
    img = ImageOps.exif_transpose(img)
    original_size = img.size
    img = img.convert("RGB")
    scale = min(1.0, max_side / max(img.size))
    if scale < 1.0:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    jpeg = buf.getvalue()
    image_id = "img_" + hashlib.sha256(jpeg).hexdigest()[:12]
    return NormalizedImage(image_id, source_name, img.width, img.height, jpeg, original_size)


def load_image(path: str | Path, max_side: int = 1600) -> NormalizedImage:
    p = Path(path)
    if not p.is_file():
        raise ImageLoadError(f"image not found: {p}")
    return normalize_image_bytes(p.read_bytes(), p.name, max_side)
