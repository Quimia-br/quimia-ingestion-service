from __future__ import annotations

from io import BytesIO
from PIL import Image


def normalize_png(image_bytes: bytes, canvas_size: int = 1254, occupancy: float = 0.88) -> bytes:
    with Image.open(BytesIO(image_bytes)) as src:
        image = src.convert("RGBA")
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            raise ValueError("imagem totalmente transparente")
        image = image.crop(bbox)
        max_side = max(1, int(canvas_size * occupancy))
        ratio = min(max_side / image.width, max_side / image.height)
        new_size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        pos = ((canvas_size - image.width) // 2, (canvas_size - image.height) // 2)
        canvas.alpha_composite(image, pos)
        out = BytesIO()
        canvas.save(out, format="PNG", optimize=True)
        return out.getvalue()
