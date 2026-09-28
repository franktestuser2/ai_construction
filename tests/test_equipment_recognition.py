"""Тесты объединения находок детектора и ответов визуально-языковой модели."""

from datetime import date
from pathlib import Path

from site_monitoring.entity import (
    ArbitrationResult,
    EquipmentSource,
    EquipmentStatus,
    ObservedEquipment,
)
from site_monitoring.services.equipment_recognition import EquipmentRecognitionService

FRAME_ID = "frame-1"
IMAGE_PATH = Path("data/photos_v2/W05/W05_2027-02-26_frame21.jpg")
OBSERVED_ON = date(2027, 1, 18)
WORK_NAME = "Устройство несущих ж/б конструкций"


class _FakeDetector:
    """Детектор-заглушка: всегда возвращает заданный набор находок."""

    def __init__(self, equipment: tuple[ObservedEquipment, ...]) -> None:
        self._equipment = equipment

    def detect(self, image_path: Path) -> tuple[ObservedEquipment, ...]:
        """Возвращает заранее заданные находки."""
        return self._equipment


class _FakeVlm:
    """Модель-заглушка: запоминает вопросы и отдаёт заданный ответ."""

    def __init__(
        self,
        equipment: tuple[ObservedEquipment, ...],
        limited_view: bool = False,
        limited_reason: str = "",
    ) -> None:
        self._equipment = equipment
        self._limited_view = limited_view
        self._limited_reason = limited_reason
        self.asked: tuple[tuple[str, str], ...] = ()

    def recognize(self, image_path: Path, work_name: str, questions: tuple[tuple[str, str], ...]):
        """Сохраняет заданные вопросы и возвращает подготовленный ответ."""
        self.asked = questions
        return self._equipment, self._limited_view, self._limited_reason


def _detector_find(machine_class: str) -> ObservedEquipment:
    """Находка детектора без сведений об активности."""
    equipment = ObservedEquipment(
        machine_type=machine_class,
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.NOT_APPLICABLE,
        count=1,
        confidence=0.09,
    )
    return equipment


def _vlm_find(machine_type: str, status: EquipmentStatus) -> ObservedEquipment:
    """Ответ модели по одному типу техники."""
    equipment = ObservedEquipment(
        machine_type=machine_type,
        source=EquipmentSource.VLM,
        status=status,
        count=1,
        justification="обоснование модели",
    )
    return equipment


def test_detector_find_gets_status_from_vlm(work_rules) -> None:
    # Arrange
    detector = _FakeDetector((_detector_find("Excavator"),))
    vlm = _FakeVlm((_vlm_find("Экскаватор", EquipmentStatus.WORKING),))
    service = EquipmentRecognitionService(detector, vlm)

    # Act
    observation = service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    excavator = next(item for item in observation.equipment if item.machine_type == "Excavator")
    assert excavator.source is EquipmentSource.DETECTOR
    assert excavator.status is EquipmentStatus.WORKING


def test_vlm_only_type_is_added(work_rules) -> None:
    # Arrange
    detector = _FakeDetector(())
    vlm = _FakeVlm((_vlm_find("Башенный кран", EquipmentStatus.WORKING),))
    service = EquipmentRecognitionService(detector, vlm)

    # Act
    observation = service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    types = [item.machine_type for item in observation.equipment]
    assert types == ["Башенный кран"]
    assert observation.equipment[0].source is EquipmentSource.VLM


def test_questions_cover_all_requirements(work_rules) -> None:
    # Arrange
    detector = _FakeDetector(())
    vlm = _FakeVlm(())
    service = EquipmentRecognitionService(detector, vlm)

    # Act
    service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    asked_types = [machine_type for machine_type, _ in vlm.asked]
    assert asked_types == ["Экскаватор", "Башенный кран"]


def test_limited_view_is_carried_from_vlm(work_rules) -> None:
    # Arrange
    detector = _FakeDetector(())
    vlm = _FakeVlm((), limited_view=True)
    service = EquipmentRecognitionService(detector, vlm)

    # Act
    observation = service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    assert observation.limited_view is True


def test_vlm_type_with_question_wording_is_matched() -> None:
    # Arrange
    from site_monitoring.adapters.vlm_client import parse_vlm_answer

    answer = {
        "техника": [
            {
                "тип": "Техника «Экскаватор»",
                "обнаружена": True,
                "статус": "работает",
                "обоснование": "ковш в грунте",
            }
        ],
        "обзор_ограничен": False,
    }

    # Act
    equipment, limited_view, _ = parse_vlm_answer(answer, ("Экскаватор", "Самосвал"))

    # Assert
    assert len(equipment) == 1
    assert equipment[0].machine_type == "Экскаватор"
    assert limited_view is False


class _FakeArbiter:
    """Арбитр-заглушка: отвечает по заранее заданному сценарию на каждую рамку."""

    def __init__(self, verdicts: tuple[ArbitrationResult, ...]) -> None:
        self._verdicts = list(verdicts)
        self.calls = 0

    def verify(self, image_path: Path, box, machine_type: str, work_name: str) -> ArbitrationResult:
        """Возвращает очередной подготовленный вывод арбитра."""
        self.calls += 1
        verdict = self._verdicts.pop(0)
        return verdict


def _arbitration(confirmed: bool, status: EquipmentStatus, actual_class: str = "Экскаватор") -> ArbitrationResult:
    """Вывод арбитра по одной рамке."""
    result = ArbitrationResult(
        confirmed=confirmed,
        actual_class=actual_class,
        status=status,
        justification="Гусеничное шасси, ковш опущен в грунт",
    )
    return result


def test_arbiter_rejects_false_detection(work_rules) -> None:
    # Arrange
    candidate = ObservedEquipment(
        machine_type="Excavator",
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.NOT_APPLICABLE,
        count=2,
        confidence=0.08,
        boxes=((0.1, 0.1, 0.2, 0.2), (0.5, 0.5, 0.7, 0.7)),
    )
    arbiter = _FakeArbiter((
        _arbitration(True, EquipmentStatus.WORKING),
        _arbitration(False, EquipmentStatus.NOT_APPLICABLE, "Куча грунта"),
    ))
    service = EquipmentRecognitionService(_FakeDetector((candidate,)), _FakeVlm(()), arbiter)

    # Act
    observation = service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    found = observation.equipment[0]
    assert arbiter.calls == 2
    assert found.count == 1
    assert found.boxes == ((0.1, 0.1, 0.2, 0.2),)
    assert found.rejected_boxes == ((0.5, 0.5, 0.7, 0.7),)
    assert found.status is EquipmentStatus.WORKING


def test_при_арбитре_модель_спрашивают_и_про_технику_детектора(work_rules) -> None:
    # Arrange: детектор нашёл рамку, но вопрос по кадру всё равно должен прозвучать
    candidate = ObservedEquipment(
        machine_type="Excavator",
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.NOT_APPLICABLE,
        count=1,
        confidence=0.08,
        boxes=((0.1, 0.1, 0.2, 0.2),),
    )
    vlm = _FakeVlm(())
    arbiter = _FakeArbiter((_arbitration(True, EquipmentStatus.WORKING),))
    service = EquipmentRecognitionService(_FakeDetector((candidate,)), vlm, arbiter)

    # Act
    service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    asked_types = {machine_type for machine_type, _ in vlm.asked}
    assert "Экскаватор" in asked_types


def test_отклонённая_рамка_не_отменяет_технику_с_кадра(work_rules) -> None:
    # Arrange: рамка легла на соседнюю машину, арбитр её отклонил,
    # но на кадре целиком модель экскаватор видит
    candidate = ObservedEquipment(
        machine_type="Excavator",
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.NOT_APPLICABLE,
        count=1,
        confidence=0.07,
        boxes=((0.39, 0.29, 0.65, 0.66),),
    )
    vlm = _FakeVlm((_vlm_find("Экскаватор", EquipmentStatus.WORKING),))
    arbiter = _FakeArbiter((_arbitration(False, EquipmentStatus.NOT_APPLICABLE, "самосвал"),))
    service = EquipmentRecognitionService(_FakeDetector((candidate,)), vlm, arbiter)

    # Act
    observation = service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    found = [item for item in observation.equipment if item.machine_type == "Экскаватор"]
    assert len(found) == 1
    assert found[0].count == 1
    assert found[0].source is EquipmentSource.VLM


def test_подтверждённая_рамка_отменяет_запасной_ответ(work_rules) -> None:
    # Arrange: и рамка подтверждена, и модель отвечает «есть» — находка должна остаться одна
    candidate = ObservedEquipment(
        machine_type="Excavator",
        source=EquipmentSource.DETECTOR,
        status=EquipmentStatus.NOT_APPLICABLE,
        count=1,
        confidence=0.09,
        boxes=((0.1, 0.1, 0.3, 0.3),),
    )
    vlm = _FakeVlm((_vlm_find("Экскаватор", EquipmentStatus.WORKING),))
    arbiter = _FakeArbiter((_arbitration(True, EquipmentStatus.WORKING),))
    service = EquipmentRecognitionService(_FakeDetector((candidate,)), vlm, arbiter)

    # Act
    observation = service.recognize_frame(FRAME_ID, IMAGE_PATH, OBSERVED_ON, WORK_NAME, work_rules)

    # Assert
    excavators = [item for item in observation.equipment
                  if item.machine_type in ("Экскаватор", "Excavator")]
    assert len(excavators) == 1
    assert excavators[0].source is EquipmentSource.DETECTOR
