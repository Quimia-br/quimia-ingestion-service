import inspect
from pathlib import Path
import re

from quimia_ingestion.core.config import Settings
from quimia_ingestion.images.normalize import normalize_png

ROOT = Path(__file__).resolve().parents[2]
EXISTING_ASSET_CANVAS = 1254  # PNGs de quimia-bd/src/database/assets/produtos


def _example(name):
    return re.search(rf"^{name}=(.+)$", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M).group(1).strip()


def test_canvas_is_1254_in_example_settings_default_and_normalize():
    assert int(_example("IMAGE_CANVAS_SIZE")) == EXISTING_ASSET_CANVAS
    assert Settings.__dataclass_fields__["image_canvas_size"].default == EXISTING_ASSET_CANVAS
    assert inspect.signature(normalize_png).parameters["canvas_size"].default == EXISTING_ASSET_CANVAS


def test_production_image_thresholds_not_lowered():
    assert float(_example("IMAGE_AUTO_APPROVE_SCORE")) == 0.90
    assert Settings.__dataclass_fields__["image_auto_approve_score"].default == 0.90
    assert Settings.__dataclass_fields__["image_review_score"].default == 0.70


def test_only_one_canvas_variable_exists():
    names = re.findall(r"^(\w*CANVAS\w*)=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M)
    assert names == ["IMAGE_CANVAS_SIZE"]
