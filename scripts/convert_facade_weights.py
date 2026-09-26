"""Перенос весов фасадных моделей из mmdetection в torchvision.

Оба детектора обучены на Faster R-CNN R50-FPN в mmdetection 1.x; поднять его
в проекте нельзя — mmcv тех версий не собирается с нынешним torch. Архитектура
стандартная, поэтому веса перекладываются под имена torchvision один раз,
а сервис дальше работает обычным `load_state_dict`.

Классификатор ограждений приходит целиком запиканным объектом `ResNet`;
из него достаётся state_dict, чтобы в рантайме не распаковывать пикл.
"""

import logging
import sys
from pathlib import Path

import torch
from torchvision import models

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from site_monitoring.adapters.facade_detector import build_faster_rcnn  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

WEIGHTS_DIR = Path("models/facade/weights")
TARGET_DIR = WEIGHTS_DIR / "torchvision"
CELL_SOURCE = WEIGHTS_DIR / "cell_pd170223.pth"
BUILDING_SOURCE = WEIGHTS_DIR / "det_building.pth"
BARRIER_SOURCE = WEIGHTS_DIR / "augon_lr1e-4_resnet18_valprecision_0.823.pt"
CELL_TARGET = TARGET_DIR / "facade_cells.pt"
BUILDING_TARGET = TARGET_DIR / "building.pt"
BARRIER_TARGET = TARGET_DIR / "barrier_resnet18.pt"
CELL_CLASS_COUNT = 3
BUILDING_CLASS_COUNT = 1
BARRIER_FEATURES = 512
BARRIER_OUTPUTS = 1
STATE_DICT_KEY = "state_dict"
BATCH_COUNTER_SUFFIX = "num_batches_tracked"
BOX_COORDINATES = 4

BACKBONE_PREFIX = "backbone."
LATERAL_PREFIX = "neck.lateral_convs."
FPN_CONV_PREFIX = "neck.fpn_convs."
RPN_CONV_PREFIX = "rpn_head.rpn_conv."
RPN_CLS_PREFIX = "rpn_head.rpn_cls."
RPN_REG_PREFIX = "rpn_head.rpn_reg."
SHARED_FC_FIRST_PREFIX = "roi_head.bbox_head.shared_fcs.0."
SHARED_FC_SECOND_PREFIX = "roi_head.bbox_head.shared_fcs.1."
CLS_PREFIX = "roi_head.bbox_head.fc_cls."
REG_PREFIX = "roi_head.bbox_head.fc_reg."

SIMPLE_PREFIX_MAP = {
    RPN_CONV_PREFIX: "rpn.head.conv.0.0.",
    RPN_CLS_PREFIX: "rpn.head.cls_logits.",
    RPN_REG_PREFIX: "rpn.head.bbox_pred.",
    SHARED_FC_FIRST_PREFIX: "roi_heads.box_head.fc6.",
    SHARED_FC_SECOND_PREFIX: "roi_heads.box_head.fc7.",
}
INDEXED_PREFIX_MAP = {
    LATERAL_PREFIX: "backbone.fpn.inner_blocks.{index}.0.{tail}",
    FPN_CONV_PREFIX: "backbone.fpn.layer_blocks.{index}.0.{tail}",
}


def _move_background_first(tensor: torch.Tensor) -> torch.Tensor:
    """Переставляет фон из последнего класса в нулевой, как ждёт torchvision."""
    last = tensor.shape[0] - 1
    order = [last] + list(range(last))
    reordered = tensor[order]
    return reordered


def _add_background_regression(tensor: torch.Tensor) -> torch.Tensor:
    """Добавляет пустой слот регрессии для фона: в mmdetection его нет."""
    zeros = torch.zeros((BOX_COORDINATES,) + tuple(tensor.shape[1:]), dtype=tensor.dtype)
    widened = torch.cat([zeros, tensor], dim=0)
    return widened


def _rename_indexed(key: str, prefix: str, template: str) -> str:
    """Собирает имя ключа для слоёв FPN, пронумерованных по уровням."""
    parts = key.split(".")
    renamed = template.format(index=parts[2], tail=parts[-1])
    return renamed


def _rename_key(key: str) -> str | None:
    """Находит имя ключа torchvision для ключа mmdetection."""
    if key.startswith(BACKBONE_PREFIX):
        return "backbone.body." + key[len(BACKBONE_PREFIX):]
    for prefix, template in INDEXED_PREFIX_MAP.items():
        if key.startswith(prefix):
            return _rename_indexed(key, prefix, template)
    for prefix, replacement in SIMPLE_PREFIX_MAP.items():
        if key.startswith(prefix):
            return replacement + key.split(".")[-1]
    return None


def convert_detector_state(state: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Перекладывает веса детектора под имена torchvision."""
    converted: dict[str, torch.Tensor] = {}
    for key, value in state.items():
        if key.endswith(BATCH_COUNTER_SUFFIX):
            continue
        if key.startswith(CLS_PREFIX):
            converted["roi_heads.box_predictor.cls_score." + key.split(".")[-1]] = _move_background_first(value)
            continue
        if key.startswith(REG_PREFIX):
            converted["roi_heads.box_predictor.bbox_pred." + key.split(".")[-1]] = _add_background_regression(value)
            continue
        renamed = _rename_key(key)
        if renamed is None:
            raise KeyError(f"Ключ без пары в torchvision: {key}")
        converted[renamed] = value
    return converted


def convert_detector(source: Path, target: Path, class_count: int) -> None:
    """Переносит один детектор и проверяет, что сеть принимает веса целиком."""
    checkpoint = torch.load(source, map_location="cpu", weights_only=False)
    converted = convert_detector_state(checkpoint[STATE_DICT_KEY])
    model = build_faster_rcnn(class_count)
    missing, unexpected = model.load_state_dict(converted, strict=False)
    if missing or unexpected:
        raise ValueError(f"Веса не сошлись: не заполнено {len(missing)}, лишних {len(unexpected)}")
    torch.save(converted, target)
    logger.info("%s → %s, тензоров %d", source.name, target.name, len(converted))


def convert_barrier(source: Path, target: Path) -> None:
    """Достаёт state_dict классификатора ограждений из запиканного объекта."""
    module = torch.load(source, map_location="cpu", weights_only=False)
    state = module.state_dict()
    model = models.resnet18(weights=None)
    model.fc = torch.nn.Linear(BARRIER_FEATURES, BARRIER_OUTPUTS, bias=True)
    model.load_state_dict(state)
    torch.save(state, target)
    logger.info("%s → %s, тензоров %d", source.name, target.name, len(state))


def main() -> int:
    """Переносит все три модели фасадной ветки."""
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    convert_detector(CELL_SOURCE, CELL_TARGET, CELL_CLASS_COUNT)
    convert_detector(BUILDING_SOURCE, BUILDING_TARGET, BUILDING_CLASS_COUNT)
    convert_barrier(BARRIER_SOURCE, BARRIER_TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
