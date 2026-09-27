"""Тесты проверки охраны труда: три исхода сравнения фраз."""

import numpy as np

from camera_watch.entity import ABSENT, PERSON_SCOPE, PRESENT, UNCLEAR, SafetyCheck
from camera_watch.services.safety_assessment import score_check

POSITIVE = "рабочий без каски"
NEGATIVE = "рабочий в каске"
BOX = (10, 20, 60, 140)


def _check(threshold: float = 0.55, strict: float = 0.75, min_margin: float = 0.002) -> SafetyCheck:
    """Проверка с заданными порогами."""
    check = SafetyCheck(
        key="нет_каски",
        title="Рабочий без защитной каски",
        scope=PERSON_SCOPE,
        positive=(POSITIVE,),
        negative=(NEGATIVE,),
        threshold=threshold,
        strict_threshold=strict,
        min_margin=min_margin,
    )
    return check


def _vectors(positive_score: float, negative_score: float) -> dict[str, np.ndarray]:
    """Фразы, чья близость к кадру задана прямо."""
    image = np.array([1.0, 0.0], dtype=np.float32)
    mapping = {
        POSITIVE: np.array([positive_score, 0.0], dtype=np.float32),
        NEGATIVE: np.array([negative_score, 0.0], dtype=np.float32),
    }
    return mapping | {"_кадр": image}


def test_заметный_отрыв_за_даёт_отметку() -> None:
    # Arrange
    check = _check()
    vectors = _vectors(0.2700, 0.2500)

    # Act
    finding = score_check(check, vectors["_кадр"], vectors, BOX)

    # Assert
    assert finding.verdict == PRESENT
    assert finding.is_violation is True


def test_отрыв_в_пользу_против_даёт_отсутствие() -> None:
    # Arrange
    check = _check()
    vectors = _vectors(0.2500, 0.2700)

    # Act
    finding = score_check(check, vectors["_кадр"], vectors, BOX)

    # Assert
    assert finding.verdict == ABSENT


def test_малый_отрыв_даёт_не_ясно_а_не_отсутствие() -> None:
    # Arrange
    check = _check()
    vectors = _vectors(0.2600, 0.2591)

    # Act
    finding = score_check(check, vectors["_кадр"], vectors, BOX)

    # Assert
    assert finding.verdict == UNCLEAR
    assert finding.is_violation is False


def test_уверенная_отметка_ставится_только_выше_строгого_порога() -> None:
    # Arrange
    check = _check()
    weak = _vectors(0.2560, 0.2500)
    strong = _vectors(0.2700, 0.2500)

    # Act
    weak_finding = score_check(check, weak["_кадр"], weak, BOX)
    strong_finding = score_check(check, strong["_кадр"], strong, BOX)

    # Assert
    assert weak_finding.confident is False
    assert strong_finding.confident is True


def test_рамка_области_сохраняется_в_находке() -> None:
    # Arrange
    check = _check()
    vectors = _vectors(0.2800, 0.2500)

    # Act
    finding = score_check(check, vectors["_кадр"], vectors, BOX)

    # Assert
    assert finding.box == BOX
    assert finding.best_positive == POSITIVE


def test_решение_обученной_сети_переводится_в_находку() -> None:
    # Arrange
    from camera_watch.entity import CLASSIFIER_MODEL
    from camera_watch.services.safety_assessment import score_probability

    check = SafetyCheck(
        key="нет_каски",
        title="Рабочий без защитной каски",
        scope=PERSON_SCOPE,
        positive=(),
        negative=(),
        threshold=0.5,
        strict_threshold=0.9,
        min_margin=0.0,
        model=CLASSIFIER_MODEL,
        weights="models/ppe/head.pt",
    )

    # Act
    sure = score_probability(check, 0.95, BOX)
    marked = score_probability(check, 0.61, BOX)
    clean = score_probability(check, 0.12, BOX)

    # Assert
    assert (sure.verdict, sure.confident) == (PRESENT, True)
    assert (marked.verdict, marked.confident) == (PRESENT, False)
    assert clean.verdict == ABSENT
