"""Проверка кадра на нарушения охраны труда.

Решение принимается сравнением, а не абсолютной близостью: лучшая фраза «за» против лучшей
фразы «против». Так устроено потому, что близости CLIP лежат в узкой полосе и значение
0,30 само по себе не означает ничего — это проверено авторами модели и подтвердилось у нас.

Исхода три. Если отрыв «за» от «против» меньше порога, ответ — «не ясно»: модель не
разделила фразы. Свести это к «нарушения нет» значило бы отчитаться об отсутствии там,
где никто ничего не увидел.
"""

import logging
from typing import Protocol

import numpy as np

from camera_watch.adapters.clip_encoder import ClipEncoder
from camera_watch.adapters.motion_regions import crop_head, crop_region
from camera_watch.adapters.ppe_classifier import PpeClassifier
from camera_watch.entity import (
    ABSENT,
    CLASSIFIER_MODEL,
    FRAME_SCOPE,
    HEAD_SCOPE,
    MOTION_SOURCE,
    PERSON_SCOPE,
    PRESENT,
    UNCLEAR,
    PersonRegion,
    SafetyCheck,
    SafetyFinding,
)


class RegionFinder(Protocol):
    """Любой способ найти людей в кадре."""

    def find(self, frames: list[np.ndarray]) -> tuple[PersonRegion, ...]:
        """Области людей на последнем кадре последовательности."""
        ...

logger = logging.getLogger(__name__)

# Масштаб логитов CLIP перед softmax взят из оригинальной модели: без него разница
# в сотую долю косинуса превращается в неразличимые 50/50.
LOGIT_SCALE = 100.0
DEFAULT_PERSON_PADDING = 30
# Ниже этой высоты вырезки судить о каске нельзя: на съёмке с дрона голова рабочего
# занимает сорок пикселей, и модель отмечала каску отсутствующей у всех подряд.
MIN_HEAD_PIXELS = 70
ROUND_DIGITS = 4


class SafetyAssessmentService:
    """Прогоняет кадр через набор проверок охраны труда."""

    def __init__(
        self,
        encoder: ClipEncoder,
        region_finders: dict[str, RegionFinder],
        checks: tuple[SafetyCheck, ...],
        person_padding: int = DEFAULT_PERSON_PADDING,
        classifiers: dict[str, PpeClassifier] | None = None,
    ) -> None:
        self._encoder = encoder
        self._region_finders = region_finders
        self._checks = checks
        self._person_padding = person_padding
        self._classifiers = classifiers or {}

    @property
    def checks(self) -> tuple[SafetyCheck, ...]:
        """Набор проверок, которым занимается сервис."""
        return self._checks

    def is_ready(self) -> bool:
        """Есть ли чем проверять: без весов проверка не запускается."""
        if not self._checks:
            return False
        ready = all(self._has_model(check) for check in self._checks)
        return ready

    def _has_model(self, check: SafetyCheck) -> bool:
        """Готова ли модель, которой решается эта проверка."""
        if check.model == CLASSIFIER_MODEL:
            classifier = self._classifiers.get(check.key)
            return classifier is not None and classifier.is_available()
        return self._encoder.is_available()

    def assess(
        self, frames: list[np.ndarray], people_source: str = ""
    ) -> tuple[tuple[PersonRegion, ...], tuple[SafetyFinding, ...]]:
        """Возвращает найденных людей и находки по всем проверкам.

        Способ поиска людей не задан — берётся единственный имеющийся: так разбор
        присланных фотографий не обязан знать про камеры и их настройки.
        """
        if not frames or not self.is_ready():
            return (), ()
        people_source = people_source or self._only_finder()
        phrases = self._all_phrases()
        vectors = self._encoder.embed_phrases(phrases) if phrases else {}
        current = frames[-1]
        findings = list(self._assess_frame(current, vectors))
        regions = self._find_people(frames, people_source)
        for region in regions:
            findings.extend(self._assess_region(current, region, vectors))
            findings.extend(self._assess_head(current, region, vectors))
        return regions, tuple(findings)

    def _only_finder(self) -> str:
        """Единственный настроенный способ поиска людей."""
        names = sorted(self._region_finders)
        return names[0] if len(names) == 1 else MOTION_SOURCE

    def _find_people(self, frames: list[np.ndarray], people_source: str) -> tuple[PersonRegion, ...]:
        """Ищет людей тем способом, который задан камере."""
        finder = self._region_finders.get(people_source)
        if finder is None:
            logger.warning("Неизвестный источник людей: %s", people_source)
            return ()
        regions = finder.find(frames)
        return regions

    def _assess_frame(self, frame: np.ndarray, vectors: dict[str, np.ndarray]) -> list[SafetyFinding]:
        """Проверки, которые смотрят на кадр целиком."""
        checks = [item for item in self._checks if item.scope == FRAME_SCOPE]
        if not checks:
            return []
        vector = self._encoder.embed_image(frame)
        findings = [score_check(check, vector, vectors, None) for check in checks]
        return findings

    def _assess_region(
        self, frame: np.ndarray, region: PersonRegion, vectors: dict[str, np.ndarray]
    ) -> list[SafetyFinding]:
        """Проверки, которые смотрят на одного человека."""
        checks = [item for item in self._checks if item.scope == PERSON_SCOPE]
        if not checks:
            return []
        piece = crop_region(frame, region, self._person_padding)
        if piece.size == 0:
            return []
        findings = [self._judge(check, piece, vectors, region.box) for check in checks]
        return findings

    def _assess_head(
        self, frame: np.ndarray, region: PersonRegion, vectors: dict[str, np.ndarray]
    ) -> list[SafetyFinding]:
        """Проверки, которые смотрят на голову человека."""
        checks = [item for item in self._checks if item.scope == HEAD_SCOPE]
        if not checks:
            return []
        piece = crop_head(frame, region)
        if piece.size == 0 or piece.shape[0] < MIN_HEAD_PIXELS:
            return []
        findings = [self._judge(check, piece, vectors, region.box) for check in checks]
        return findings

    def _judge(
        self,
        check: SafetyCheck,
        piece: np.ndarray,
        vectors: dict[str, np.ndarray],
        box: tuple[int, int, int, int],
    ) -> SafetyFinding:
        """Выносит решение по вырезке тем способом, который задан проверке."""
        if check.model == CLASSIFIER_MODEL:
            share = self._classifiers[check.key].violation_probability(piece)
            return score_probability(check, share, box)
        vector = self._encoder.embed_image(piece)
        finding = score_check(check, vector, vectors, box)
        return finding

    def _all_phrases(self) -> list[str]:
        """Все формулировки проверок, решаемых сравнением фраз."""
        phrases: list[str] = []
        for check in self._checks:
            if check.model == CLASSIFIER_MODEL:
                continue
            phrases.extend(check.positive)
            phrases.extend(check.negative)
        return phrases


def score_probability(
    check: SafetyCheck, share: float, box: tuple[int, int, int, int] | None
) -> SafetyFinding:
    """Переводит вероятность обученной сети в находку.

    «Не ясно» здесь не бывает: сеть отвечает вероятностью, и отказываться от ответа ей
    незачем — отказ нужен был сравнению фраз, где малый отрыв означал, что модель
    формулировки не разделила.
    """
    finding = SafetyFinding(
        check_key=check.key,
        title=check.title,
        verdict=PRESENT if share >= check.threshold else ABSENT,
        confidence=round(share, ROUND_DIGITS),
        confident=share >= check.strict_threshold,
        margin=round(share - check.threshold, ROUND_DIGITS),
        best_positive=check.title,
        best_negative="",
        box=box,
    )
    return finding


def score_check(
    check: SafetyCheck,
    image_vector: np.ndarray,
    phrase_vectors: dict[str, np.ndarray],
    box: tuple[int, int, int, int] | None,
) -> SafetyFinding:
    """Сравнивает лучшую фразу «за» с лучшей фразой «против» и выносит один из трёх исходов."""
    best_positive = _best_phrase(check.positive, image_vector, phrase_vectors)
    best_negative = _best_phrase(check.negative, image_vector, phrase_vectors)
    margin = best_positive[1] - best_negative[1]
    confidence = _confidence(best_positive[1], best_negative[1])
    finding = SafetyFinding(
        check_key=check.key,
        title=check.title,
        verdict=_verdict(check, confidence, margin),
        confidence=round(confidence, ROUND_DIGITS),
        confident=confidence >= check.strict_threshold and abs(margin) >= check.min_margin,
        margin=round(margin, ROUND_DIGITS),
        best_positive=best_positive[0],
        best_negative=best_negative[0],
        box=box,
    )
    return finding


def _best_phrase(
    phrases: tuple[str, ...], image_vector: np.ndarray, phrase_vectors: dict[str, np.ndarray]
) -> tuple[str, float]:
    """Самая близкая к кадру формулировка из набора.

    Максимум, а не среднее: формулировки описывают разные проявления одного признака,
    и среднее наказывало бы за подробно расписанный набор.
    """
    scored = [
        (phrase, float(phrase_vectors[phrase] @ image_vector))
        for phrase in phrases
        if phrase in phrase_vectors
    ]
    if not scored:
        return "", 0.0
    best = max(scored, key=lambda item: item[1])
    return best


def _confidence(positive_score: float, negative_score: float) -> float:
    """Уверенность «за» после softmax по двум близостям."""
    logits = np.array([positive_score, negative_score], dtype=np.float64) * LOGIT_SCALE
    shifted = np.exp(logits - logits.max())
    share = float(shifted[0] / shifted.sum())
    return share


def _verdict(check: SafetyCheck, confidence: float, margin: float) -> str:
    """Три исхода проверки: признак есть, признака нет, сравнение не разделило фразы."""
    if abs(margin) < check.min_margin:
        return UNCLEAR
    outcome = PRESENT if confidence >= check.threshold else ABSENT
    return outcome
