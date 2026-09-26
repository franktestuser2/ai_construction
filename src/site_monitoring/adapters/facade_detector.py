"""Детекторы фасада: ячейки проёмов и здание целиком.

Веса обучены в mmdetection на архитектуре Faster R-CNN R50-FPN в caffe-варианте;
здесь та же сеть собирается средствами torchvision, чтобы сервис жил одним
процессом без mmcv. Веса заранее переложены под имена torchvision, поэтому
адаптер читает готовый state_dict и никакого пикла не распаковывает.
"""

import logging
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision.models.detection.backbone_utils import resnet_fpn_backbone
from torchvision.models.detection.faster_rcnn import FasterRCNN
from torchvision.ops import MultiScaleRoIAlign, roi_align
from torchvision.ops.poolers import _convert_to_roi_format, _filter_input, _setup_scales

from ..entity import BuildingBox, FacadeCell, FacadeCellKind

logger = logging.getLogger(__name__)

BACKBONE_NAME = "resnet50"
FEATURE_MAP_NAMES = ["0", "1", "2", "3"]
POOLER_OUTPUT_SIZE = 7
POOLER_SAMPLING_RATIO = -1
MIN_IMAGE_SIDE = 800
MAX_IMAGE_SIDE = 1333
# Значения из рабочей конфигурации авторов: nms_pre и max_per_img подняты под фасад,
# на котором рамок в разы больше, чем на обычном снимке COCO.
RPN_PRE_NMS_TOP_N = 3000
RPN_POST_NMS_TOP_N = 2000
RPN_NMS_THRESHOLD = 0.7
BOX_SCORE_THRESHOLD = 0.05
BOX_NMS_THRESHOLD = 0.5
MAX_DETECTIONS_PER_IMAGE = 1000
# Веса caffe-варианта ждут кадр в BGR и без деления на стандартное отклонение.
CAFFE_PIXEL_MEAN = (103.530, 116.280, 123.675)
CAFFE_PIXEL_STD = (1.0, 1.0, 1.0)
PIXEL_RANGE = 255.0
STRIDED_LAYER_NAMES = ("layer2", "layer3", "layer4")
UNIT_STRIDE = (1, 1)
CELL_CLASS_COUNT = 3
BUILDING_CLASS_COUNT = 1
BUILDING_LABEL = 1
# Порядок классов задан обучением: 0 — окно, 1 — пустой проём, 2 — заложенный.
CELL_KIND_BY_LABEL = {
    1: FacadeCellKind.WINDOW,
    2: FacadeCellKind.MONOLITH,
    3: FacadeCellKind.BLOCK,
}
EMPTY_LEVEL = 0
BOXES_KEY = "boxes"
SCORES_KEY = "scores"
LABELS_KEY = "labels"


class AlignedRoiPooler(MultiScaleRoIAlign):
    """RoIAlign со сдвигом сетки на полпикселя, как в mmcv.

    torchvision вырезает область без этого сдвига, а веса обучены с ним.
    Разница небольшая, но на мелких ячейках фасада она стоит заметной доли точности.
    """

    def forward(
        self,
        x: dict[str, torch.Tensor],
        boxes: list[torch.Tensor],
        image_shapes: list[tuple[int, int]],
    ) -> torch.Tensor:
        """Вырезает признаки по рамкам с того уровня пирамиды, куда рамка попадает."""
        features = _filter_input(x, self.featmap_names)
        if self.scales is None or self.map_levels is None:
            self.scales, self.map_levels = _setup_scales(
                features, image_shapes, self.canonical_scale, self.canonical_level
            )
        rois = _convert_to_roi_format(boxes)
        levels = self.map_levels(boxes)
        pooled = self._pool_by_level(features, rois, levels)
        return pooled

    def _pool_by_level(
        self,
        features: list[torch.Tensor],
        rois: torch.Tensor,
        levels: torch.Tensor,
    ) -> torch.Tensor:
        """Собирает вырезанные признаки всех уровней в один тензор."""
        sample = features[0]
        shape = (rois.shape[0], sample.shape[1]) + self.output_size
        result = torch.zeros(shape, dtype=sample.dtype, device=sample.device)
        for level, (feature, scale) in enumerate(zip(features, self.scales)):
            index = torch.where(levels == level)[0]
            if index.numel() == EMPTY_LEVEL:
                continue
            result[index] = roi_align(
                feature,
                rois[index],
                output_size=self.output_size,
                spatial_scale=scale,
                sampling_ratio=self.sampling_ratio,
                aligned=True,
            ).to(result.dtype)
        return result


def build_faster_rcnn(class_count: int) -> FasterRCNN:
    """Собирает Faster R-CNN R50-FPN в том же виде, в каком его обучали в mmdetection."""
    backbone = resnet_fpn_backbone(backbone_name=BACKBONE_NAME, weights=None, trainable_layers=5)
    pooler = AlignedRoiPooler(
        featmap_names=FEATURE_MAP_NAMES,
        output_size=POOLER_OUTPUT_SIZE,
        sampling_ratio=POOLER_SAMPLING_RATIO,
    )
    model = FasterRCNN(
        backbone,
        num_classes=class_count + 1,
        min_size=MIN_IMAGE_SIDE,
        max_size=MAX_IMAGE_SIDE,
        image_mean=[value / PIXEL_RANGE for value in CAFFE_PIXEL_MEAN],
        image_std=[value / PIXEL_RANGE for value in CAFFE_PIXEL_STD],
        rpn_pre_nms_top_n_test=RPN_PRE_NMS_TOP_N,
        rpn_post_nms_top_n_test=RPN_POST_NMS_TOP_N,
        rpn_nms_thresh=RPN_NMS_THRESHOLD,
        box_roi_pool=pooler,
        box_score_thresh=BOX_SCORE_THRESHOLD,
        box_nms_thresh=BOX_NMS_THRESHOLD,
        box_detections_per_img=MAX_DETECTIONS_PER_IMAGE,
    )
    _apply_caffe_stride(model)
    return model


def _apply_caffe_stride(model: FasterRCNN) -> None:
    """Переносит шаг свёртки с 3x3 на 1x1: так устроен caffe-вариант ResNet.

    В torchvision шаг стоит на 3x3, в caffe — на первой 1x1, флага для этого нет,
    поэтому у первых блоков трёх последних слоёв шаги меняются местами.
    """
    body = model.backbone.body
    for layer_name in STRIDED_LAYER_NAMES:
        block = getattr(body, layer_name)[0]
        stride = block.conv2.stride
        block.conv1.stride = stride
        block.conv2.stride = UNIT_STRIDE


def _to_pixels(
    crop: tuple[float, float, float, float],
    size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Переводит рамку из долей кадра в пиксели."""
    width, height = size
    scale = (width, height, width, height)
    pixels = tuple(int(value * side) for value, side in zip(crop, scale))
    return pixels  # type: ignore[return-value]


def read_image_as_bgr_tensor(
    image_path: Path,
    crop: tuple[float, float, float, float] | None = None,
) -> torch.Tensor:
    """Читает снимок в тензор BGR, как его видела модель при обучении.

    Если задана рамка, в тензор идёт только вырезанный по ней кусок: ячейки ищутся
    внутри здания, иначе они находятся и на соседних домах в кадре. Рамка задаётся
    в долях кадра — так её не приходится пересчитывать при смене разрешения.
    """
    image = Image.open(image_path).convert("RGB")
    if crop is not None:
        image = image.crop(_to_pixels(crop, image.size))
    array = np.asarray(image).astype("float32")
    reversed_channels = array[:, :, ::-1].copy()
    tensor = torch.from_numpy(reversed_channels).permute(2, 0, 1) / PIXEL_RANGE
    return tensor


class FacadeCellDetector:
    """Адаптер поиска ячеек фасада: монолит, блок, окно."""

    def __init__(self, weights_path: Path, confidence_threshold: float) -> None:
        self._weights_path = weights_path
        self._confidence_threshold = confidence_threshold
        self._model: FasterRCNN | None = None

    def load(self) -> None:
        """Поднимает модель в память один раз на весь прогон."""
        if self._model is not None:
            return
        model = build_faster_rcnn(CELL_CLASS_COUNT)
        state = torch.load(self._weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()
        self._model = model
        logger.info("Детектор ячеек фасада загружен: %s", self._weights_path.name)

    def detect(
        self,
        image_path: Path,
        crop: tuple[float, float, float, float] | None = None,
    ) -> tuple[FacadeCell, ...]:
        """Находит ячейки фасада и возвращает их рамки в долях исходного кадра."""
        self.load()
        tensor = read_image_as_bgr_tensor(image_path, crop)
        with torch.no_grad():
            outputs = self._model([tensor])
        frame = (tensor.shape[2], tensor.shape[1])
        cells = self._collect_cells(outputs[0], crop, frame)
        logger.info("На снимке %s найдено ячеек: %d", image_path.name, len(cells))
        return cells

    def _collect_cells(
        self,
        output: dict[str, torch.Tensor],
        crop: tuple[float, float, float, float] | None,
        frame: tuple[int, int],
    ) -> tuple[FacadeCell, ...]:
        """Превращает вывод сети в ячейки фасада, отбрасывая слабые находки."""
        cells: list[FacadeCell] = []
        triples = zip(output[BOXES_KEY], output[SCORES_KEY], output[LABELS_KEY])
        for box, score, label in triples:
            value = float(score)
            kind = CELL_KIND_BY_LABEL.get(int(label))
            if value < self._confidence_threshold or kind is None:
                continue
            corners = _to_frame_ratio(box, crop, frame)
            cell = FacadeCell(kind=kind, box=corners, score=value)
            cells.append(cell)
        return tuple(cells)


def _to_frame_ratio(
    box: torch.Tensor,
    crop: tuple[float, float, float, float] | None,
    frame: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Переводит рамку из пикселей вырезанного куска в доли исходного кадра."""
    width, height = frame
    ratios = [float(box[0]) / width, float(box[1]) / height, float(box[2]) / width, float(box[3]) / height]
    if crop is None:
        return tuple(ratios)  # type: ignore[return-value]
    left, top, right, bottom = crop
    span = (right - left, bottom - top)
    corners = (
        left + ratios[0] * span[0],
        top + ratios[1] * span[1],
        left + ratios[2] * span[0],
        top + ratios[3] * span[1],
    )
    return corners


class BuildingDetector:
    """Адаптер поиска здания на снимке: по нему обрезается кадр под разбор фасада."""

    def __init__(self, weights_path: Path, confidence_threshold: float) -> None:
        self._weights_path = weights_path
        self._confidence_threshold = confidence_threshold
        self._model: FasterRCNN | None = None

    def load(self) -> None:
        """Поднимает модель в память один раз на весь прогон."""
        if self._model is not None:
            return
        model = build_faster_rcnn(BUILDING_CLASS_COUNT)
        state = torch.load(self._weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()
        self._model = model
        logger.info("Детектор зданий загружен: %s", self._weights_path.name)

    def detect(self, image_path: Path) -> BuildingBox | None:
        """Возвращает самое уверенное здание на снимке либо ничего."""
        self.load()
        tensor = read_image_as_bgr_tensor(image_path)
        with torch.no_grad():
            outputs = self._model([tensor])
        frame = (tensor.shape[2], tensor.shape[1])
        building = self._select_building(outputs[0], frame)
        if building is None:
            logger.info("На снимке %s здание не найдено", image_path.name)
        return building

    def _select_building(
        self,
        output: dict[str, torch.Tensor],
        frame: tuple[int, int],
    ) -> BuildingBox | None:
        """Берёт самую уверенную рамку здания выше порога, в долях кадра."""
        pairs = zip(output[BOXES_KEY], output[SCORES_KEY], output[LABELS_KEY])
        for box, score, label in pairs:
            value = float(score)
            if int(label) != BUILDING_LABEL or value < self._confidence_threshold:
                continue
            corners = _to_frame_ratio(box, None, frame)
            building = BuildingBox(box=corners, score=value)
            return building
        return None
