from __future__ import annotations

from io import BytesIO
import math
from PIL import Image, ImageChops, ImageFilter, ImageStat

from quimia_ingestion.domain.models import ImageQualityReport


def _outer_frame_ratio(alpha: Image.Image, frame_ratio: float) -> float:
    """Fração da moldura externa (frame_ratio de cada lado) que é transparente (alpha < 16)."""
    width, height = alpha.size
    border = max(1, math.ceil(min(width, height) * frame_ratio))
    inner = alpha.crop((border, border, width - border, height - border))
    total = width * height - inner.width * inner.height
    transparent_all = alpha.histogram()[:16]
    transparent_inner = inner.histogram()[:16]
    return (sum(transparent_all) - sum(transparent_inner)) / max(1, total)


def _background_color(original: Image.Image, frame_ratio: float) -> tuple[int, int, int] | None:
    """Cor do fundo da foto original (mediana da moldura externa); None se a original já era transparente."""
    rgba = original.convert("RGBA")
    width, height = rgba.size
    border = max(1, math.ceil(min(width, height) * frame_ratio))
    frame = Image.new("L", rgba.size, 255)
    frame.paste(0, (border, border, width - border, height - border))
    if ImageStat.Stat(rgba.getchannel("A"), mask=frame).mean[0] < 128:
        return None
    return tuple(int(v) for v in ImageStat.Stat(rgba.convert("RGB"), mask=frame).median)


def _count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def _halo_ratio(rgba: Image.Image, background: tuple[int, int, int], tolerance: int = 40) -> float:
    """Quanto o contorno do recorte (2 px externos) parece mais com o fundo original que o interior do produto.

    Halo = sobra do fundo grudada no contorno. Subtrair o interior (> 8 px da borda) evita falso positivo de
    produto branco em fundo branco; usar o interior inteiro, e não uma faixa rasa, evita que halo grosso se anule.
    """
    mask = rgba.getchannel("A").point(lambda v: 255 if v >= 64 else 0)
    eroded_2 = mask.filter(ImageFilter.MinFilter(5))
    ring = ImageChops.subtract(mask, eroded_2)
    band = mask.filter(ImageFilter.MinFilter(17))
    if not _count(ring) or not _count(band):
        return 0.0
    diff = ImageChops.difference(rgba.convert("RGB"), Image.new("RGB", rgba.size, background))
    r, g, b = diff.split()
    bg_like = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v < tolerance else 0)
    ring_ratio = _count(ImageChops.multiply(bg_like, ring)) / _count(ring)
    band_ratio = _count(ImageChops.multiply(bg_like, band)) / _count(band)
    return max(0.0, ring_ratio - band_ratio)


def validate_cutout(
    image_bytes: bytes,
    *,
    original: bytes | None = None,
    min_object_size: int = 256,
    outer_frame_ratio: float = 0.03,
    required_outer_transparency: float = 0.98,
    max_halo_ratio: float = 0.25,
) -> ImageQualityReport:
    """Valida a saída do rembg ANTES de normalizar.

    Fundo residual, moldura e produto cortado precisam ser vistos aqui: o normalize recorta o objeto e o
    recoloca com margem transparente, o que esconderia esses defeitos da checagem de borda.
    `original` é a foto antes do rembg; sem ela (ou se já era transparente) não há como medir halo.
    """
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            rgba = image.convert("RGBA")
    except Exception:
        return ImageQualityReport(False, ("arquivo de imagem inválido",))

    reasons: list[str] = []
    alpha = rgba.getchannel("A")
    bbox = alpha.point(lambda v: 255 if v >= 16 else 0).getbbox()
    if bbox is None:
        return ImageQualityReport(False, ("imagem está totalmente transparente",))

    frame = _outer_frame_ratio(alpha, outer_frame_ratio)
    if frame < required_outer_transparency:
        reasons.append("fundo/borda não removidos ou produto encostando na borda (possível corte)")
    # Maior lado: é ele que define o quanto o normalize amplia. O menor lado reprovava garrafa alta e estreita
    # (227x956 px) mesmo com quase 1000 px de resolução útil.
    if max(bbox[2] - bbox[0], bbox[3] - bbox[1]) < min_object_size:
        reasons.append("produto pequeno demais na imagem original")
    halo = 0.0
    if original is not None:
        try:
            with Image.open(BytesIO(original)) as source:
                background = _background_color(source, outer_frame_ratio)
        except Exception:
            background = None
        # ponytail: sem cor de fundo conhecida (original já recortada) o halo não é medido; o frame ainda vale.
        if background is not None:
            halo = _halo_ratio(rgba, background)
            if halo > max_halo_ratio:
                reasons.append("halo/franja da cor do fundo no contorno do produto")

    return ImageQualityReport(
        accepted=not reasons,
        reasons=tuple(reasons),
        width=rgba.width,
        height=rgba.height,
        outer_frame_transparent_ratio=frame,
        halo_ratio=halo,
    )


def validate_png(
    image_bytes: bytes,
    *,
    canvas_size: int | None = None,
    min_size: int = 256,
    outer_frame_ratio: float = 0.03,
    required_outer_transparency: float = 0.98,
) -> ImageQualityReport:
    """Valida o PNG final (já normalizado): formato, RGBA, canvas e transparência real."""
    reasons: list[str] = []
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format != "PNG":
                reasons.append("arquivo não é PNG real")
            if image.mode != "RGBA":
                reasons.append("PNG não está em RGBA")
            rgba = image.convert("RGBA")
    except Exception:
        return ImageQualityReport(False, ("arquivo de imagem inválido",))

    width, height = rgba.size
    if width < min_size or height < min_size:
        reasons.append("resolução abaixo do mínimo")
    if width != height:
        reasons.append("canvas precisa ser quadrado")
    if canvas_size and (width, height) != (canvas_size, canvas_size):
        reasons.append(f"canvas diferente do padrão {canvas_size}x{canvas_size}")

    alpha = rgba.getchannel("A")
    histogram = alpha.histogram()
    total = max(1, width * height)
    transparent = sum(histogram[:250])
    if transparent == 0:
        reasons.append("imagem não possui transparência real")
    if transparent == total:
        reasons.append("imagem está totalmente transparente")

    frame = _outer_frame_ratio(alpha, outer_frame_ratio)
    if frame < required_outer_transparency:
        reasons.append("borda externa contém pixels visíveis/coloridos")

    return ImageQualityReport(
        accepted=not reasons,
        reasons=tuple(reasons),
        width=width,
        height=height,
        transparent_ratio=transparent / total,
        outer_frame_transparent_ratio=frame,
    )
