"""Распознавание техники на снимке двумя источниками.

Детектор даёт кандидатов с рамками, арбитр на базе визуально-языковой модели
проверяет каждую рамку по фрагменту и целому кадру, а типы техники, которых в
детекторе нет, модель ищет по снимку целиком.
"""

import logging
from datetime import date
from pathlib import Path

from ..adapters.detection_arbiter import DetectionArbiter
from ..adapters.equipment_detector import EquipmentDetector
from ..adapters.vlm_client import VlmClient
from ..entity import (
    EquipmentSource,
    EquipmentStatus,
    FrameObservation,
    ObservedEquipment,
    PositionAlternative,
    WorkEquipmentRules,
)

logger = logging.getLogger(__name__)

ACTIVITY_QUESTION = "Есть ли такая техника на снимке и работает ли она сейчас?"
REJECTED_TEMPLATE = "Арбитр отклонил гипотезу детектора: {reasons}"


class EquipmentRecognitionService:
    """Собирает наблюдение по одному снимку из ответов детектора и модели."""

    def __init__(
        self,
        detector: EquipmentDetector,
        vlm_client: VlmClient,
        arbiter: DetectionArbiter | None = None,
    ) -> None:
        self._detector = detector
        self._vlm_client = vlm_client
        self._arbiter = arbiter

    def recognize_frame(
        self,
        frame_id: str,
        image_path: Path,
        observed_on: date,
        work_name: str,
        rules: WorkEquipmentRules,
    ) -> FrameObservation:
        """Разбирает снимок и возвращает перечень найденной техники."""
        detected = self._detector.detect(image_path)
        questions = self._build_questions(rules)
        recognized, limited_view = self._vlm_client.recognize(image_path, work_name, questions)
        if self._arbiter is not None:
            enriched = self._verify_detections(detected, rules, image_path, work_name)
        else:
            statuses = {item.machine_type: item.status for item in recognized}
            enriched = self._apply_statuses(detected, rules, statuses)
        vlm_only = tuple(item for item in recognized if not self._is_detector_type(item.machine_type, rules))
        observation = FrameObservation(
            frame_id=frame_id,
            observed_on=observed_on,
            equipment=enriched + vlm_only,
            limited_view=limited_view,
        )
        logger.info("Снимок %s: позиций техники %d", frame_id, len(observation.equipment))
        return observation

    def _build_questions(self, rules: WorkEquipmentRules) -> tuple[tuple[str, str], ...]:
        """Готовит вопросы по снимку целиком: о признаках работ и технике вне словаря детектора."""
        questions = []
        for alternative in self._alternatives(rules):
            if alternative.source is EquipmentSource.VLM and alternative.vlm_question:
                questions.append((alternative.machine_type, alternative.vlm_question))
                continue
            if self._arbiter is None:
                questions.append((alternative.machine_type, ACTIVITY_QUESTION))
        result = tuple(questions)
        return result

    def _alternatives(self, rules: WorkEquipmentRules) -> tuple[PositionAlternative, ...]:
        """Разворачивает позиции правил в плоский перечень альтернатив."""
        alternatives = tuple(item for position in rules.positions for item in position.alternatives)
        return alternatives

    def _verify_detections(
        self,
        detected: tuple[ObservedEquipment, ...],
        rules: WorkEquipmentRules,
        image_path: Path,
        work_name: str,
    ) -> tuple[ObservedEquipment, ...]:
        """Проверяет арбитром рамки тех классов, которые участвуют в правилах этапа."""
        verified = []
        for item in detected:
            requirement = self._requirement_for_class(item.machine_type, rules)
            if requirement is None:
                verified.append(item)
                continue
            verified.append(self._verify_item(item, requirement, image_path, work_name))
        result = tuple(verified)
        return result

    def _verify_item(
        self,
        item: ObservedEquipment,
        requirement: PositionAlternative,
        image_path: Path,
        work_name: str,
    ) -> ObservedEquipment:
        """Проводит арбитраж по каждой рамке одного класса и пересобирает находку."""
        confirmed: list[tuple[float, float, float, float]] = []
        rejected: list[tuple[float, float, float, float]] = []
        accepted_reasons: list[str] = []
        rejected_reasons: list[str] = []
        status = EquipmentStatus.NOT_APPLICABLE
        for box in item.boxes:
            verdict = self._arbiter.verify(image_path, box, requirement.machine_type, work_name)  # type: ignore[union-attr]
            if not verdict.confirmed:
                rejected.append(box)
                rejected_reasons.append(f"{verdict.actual_class}. {verdict.justification}")
                continue
            confirmed.append(box)
            accepted_reasons.append(verdict.justification)
            if verdict.status is EquipmentStatus.WORKING:
                status = EquipmentStatus.WORKING
            elif status is EquipmentStatus.NOT_APPLICABLE:
                status = verdict.status
        justification = self._merge_reasons(accepted_reasons, rejected_reasons)
        updated = ObservedEquipment(
            machine_type=item.machine_type,
            source=item.source,
            status=status,
            count=len(confirmed),
            confidence=item.confidence,
            justification=justification,
            boxes=tuple(confirmed),
            rejected_boxes=tuple(rejected),
        )
        return updated

    def _merge_reasons(self, accepted: list[str], rejected: list[str]) -> str:
        """Складывает обоснования арбитра в один текст для отчёта и стенда."""
        if accepted:
            return " ".join(accepted)
        if rejected:
            return REJECTED_TEMPLATE.format(reasons=" ".join(rejected))
        return ""

    def _requirement_for_class(self, detector_class: str, rules: WorkEquipmentRules) -> PositionAlternative | None:
        """Находит альтернативу правил, к которой относится класс детектора."""
        for alternative in self._alternatives(rules):
            if detector_class in alternative.detector_classes:
                return alternative
        return None

    def _apply_statuses(
        self,
        detected: tuple[ObservedEquipment, ...],
        rules: WorkEquipmentRules,
        statuses: dict[str, EquipmentStatus],
    ) -> tuple[ObservedEquipment, ...]:
        """Проставляет находкам детектора состояние, определённое моделью."""
        enriched = []
        for item in detected:
            machine_type = self._machine_type_for_class(item.machine_type, rules)
            status = statuses.get(machine_type, EquipmentStatus.NOT_APPLICABLE) if machine_type else item.status
            updated = ObservedEquipment(
                machine_type=item.machine_type,
                source=item.source,
                status=status,
                count=item.count,
                confidence=item.confidence,
                justification=item.justification,
                boxes=item.boxes,
            )
            enriched.append(updated)
        result = tuple(enriched)
        return result

    def _machine_type_for_class(self, detector_class: str, rules: WorkEquipmentRules) -> str | None:
        """Находит название машины из правил по классу детектора."""
        alternative = self._requirement_for_class(detector_class, rules)
        if alternative is None:
            return None
        return alternative.machine_type

    def _is_detector_type(self, machine_type: str, rules: WorkEquipmentRules) -> bool:
        """Проверяет, закрывается ли эта машина детектором."""
        for alternative in self._alternatives(rules):
            if alternative.machine_type == machine_type:
                return alternative.source is EquipmentSource.DETECTOR
        return False
