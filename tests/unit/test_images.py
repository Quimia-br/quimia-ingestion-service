from io import BytesIO
from PIL import Image, ImageDraw

from quimia_ingestion.images.normalize import normalize_png
from quimia_ingestion.images.quality import validate_png


def png_bytes(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_quality_rejects_no_transparency():
    image = Image.new("RGB", (512, 512), "white")
    report = validate_png(png_bytes(image))
    assert not report.accepted
    assert any("transparência real" in r for r in report.reasons)


def test_quality_rejects_colored_outer_border():
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 511, 511), outline=(255, 0, 0, 255), width=10)
    draw.rectangle((180, 100, 330, 420), fill=(0, 0, 255, 255))
    report = validate_png(png_bytes(image))
    assert not report.accepted
    assert any("borda externa" in r for r in report.reasons)


def test_quality_accepts_centered_transparent_png():
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((190, 80, 320, 430), fill=(30, 80, 180, 255))
    report = validate_png(png_bytes(image))
    assert report.accepted


def test_normalize_outputs_square_rgba_with_margin():
    image = Image.new("RGBA", (200, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((30, 20, 170, 390), fill=(10, 20, 30, 255))
    normalized = normalize_png(png_bytes(image), canvas_size=512)
    with Image.open(BytesIO(normalized)) as result:
        assert result.size == (512, 512)
        assert result.mode == "RGBA"
    assert validate_png(normalized).accepted


# --- gate em duas etapas: recorte (antes do normalize) e PNG final -------------------------------

from quimia_ingestion.images.quality import validate_cutout


def cutout(size=(600, 800), box=(150, 100, 450, 700), color=(200, 30, 30, 255), rim=None, rim_px=3):
    """Recorte sintético: produto retangular em fundo transparente, opcionalmente com franja `rim`."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rim:
        x0, y0, x1, y1 = box
        draw.rectangle((x0 - rim_px, y0 - rim_px, x1 + rim_px, y1 + rim_px), fill=rim)
    draw.rectangle(box, fill=color)
    return png_bytes(image)


def original_bg(color, size=(600, 800)):
    return png_bytes(Image.new("RGB", size, color))


def test_white_background_kept_by_rembg_is_rejected_before_normalize():
    # Bug antigo: normalize adicionava margem transparente e o fundo branco passava na checagem de borda.
    photo = Image.new("RGBA", (600, 800), (255, 255, 255, 255))
    ImageDraw.Draw(photo).rectangle((150, 100, 450, 700), fill=(200, 30, 30, 255))
    assert validate_png(normalize_png(png_bytes(photo))).accepted  # o PNG final sozinho não percebe
    report = validate_cutout(png_bytes(photo))
    assert not report.accepted
    assert any("fundo/borda" in r for r in report.reasons)


def test_clean_cutout_is_accepted():
    assert validate_cutout(cutout(), original=original_bg("white")).accepted


def test_white_halo_from_original_background_is_rejected():
    report = validate_cutout(cutout(rim=(255, 255, 255, 255)), original=original_bg("white"))
    assert not report.accepted
    assert any("halo" in r for r in report.reasons)


def test_colored_fringe_is_rejected():
    report = validate_cutout(cutout(rim=(40, 200, 60, 255)), original=original_bg((40, 200, 60)))
    assert any("halo" in r for r in report.reasons)


def test_white_product_on_white_background_is_not_a_halo():
    report = validate_cutout(cutout(color=(250, 250, 250, 255)), original=original_bg("white"))
    assert report.accepted, report.reasons


def test_product_touching_edge_is_rejected_as_possible_crop():
    report = validate_cutout(cutout(box=(150, 100, 450, 799)))
    assert any("possível corte" in r for r in report.reasons)


def test_small_product_is_rejected():
    report = validate_cutout(cutout(box=(250, 300, 350, 420)))
    assert any("pequeno demais" in r for r in report.reasons)


def test_tall_narrow_bottle_is_not_rejected_as_small():
    # 200x700 px: menor lado < 256, mas o maior lado tem resolução de sobra.
    report = validate_cutout(cutout(box=(200, 50, 400, 750)))
    assert not any("pequeno demais" in r for r in report.reasons)


def test_final_png_rejects_jpeg_and_wrong_canvas():
    jpeg = BytesIO()
    Image.open(BytesIO(normalize_png(cutout(), canvas_size=1254))).convert("RGB").save(jpeg, "JPEG")
    assert any("PNG real" in r for r in validate_png(jpeg.getvalue()).reasons)
    assert any("padrão 1254" in r for r in validate_png(normalize_png(cutout(), canvas_size=512), canvas_size=1254).reasons)


def test_rembg_remover_reuses_one_session(monkeypatch):
    import sys
    import types

    from quimia_ingestion.images.background import RembgBackgroundRemover

    sessions = []
    fake = types.SimpleNamespace(
        new_session=lambda model: sessions.append(model) or object(),
        remove=lambda data, session: data + b"-cut",
    )
    monkeypatch.setitem(sys.modules, "rembg", fake)
    remover = RembgBackgroundRemover()
    assert remover.remove(b"a") == b"a-cut"
    assert remover.remove(b"b") == b"b-cut"
    assert sessions == ["u2net"]
