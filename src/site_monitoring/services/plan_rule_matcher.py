"""Сопоставление этапов загруженного плана с правилами по технике.

В календарном плане заказчика сведений о технике нет — это оговорено в требованиях.
Правила «этап работ → необходимая техника» заводит команда, и связать их с планом
можно только по названию этапа.

Сравниваются значимые слова названия: служебные предлоги и общие слова вроде
«устройство» или «работы» встречаются почти в каждом этапе и ничего не различают.
"""

import logging
import re

logger = logging.getLogger(__name__)

WORD_PATTERN = re.compile(r"[а-яёa-z0-9]+")
STOP_WORDS = frozenset(
    {
        "и", "в", "на", "с", "по", "для", "из", "от", "до", "под", "над", "при", "к", "т", "ч",
        "работы", "работ", "устройство", "выполнение", "монтаж", "монтажных", "строительно",
        "части", "часть", "конструкции", "конструкций", "прочие", "иные", "др", "том", "числе",
    }
)
MIN_SCORE = 0.34
SHORT_WORD_LENGTH = 3


def _significant_words(title: str) -> set[str]:
    """Выделяет из названия этапа слова, по которым его можно узнать."""
    words = WORD_PATTERN.findall(title.lower())
    meaningful = {word for word in words if word not in STOP_WORDS and len(word) > SHORT_WORD_LENGTH}
    return meaningful


def _similarity(first: set[str], second: set[str]) -> float:
    """Доля общих значимых слов в меньшем из двух названий."""
    if not first or not second:
        return 0.0
    shared = len(first & second)
    score = shared / min(len(first), len(second))
    return score


def match_work_id(title: str, known_titles: dict[str, str]) -> str | None:
    """Подбирает вид работ из правил, ближе всего совпадающий по названию."""
    words = _significant_words(title)
    best_id: str | None = None
    best_score = MIN_SCORE
    for work_id, known in known_titles.items():
        score = _similarity(words, _significant_words(known))
        if score > best_score:
            best_id, best_score = work_id, score
    if best_id is None:
        logger.info("Для этапа «%s» правила по технике не нашлись", title[:60])
    return best_id


def match_stages(
    titles: tuple[str, ...],
    known_titles: dict[str, str],
) -> tuple[str | None, ...]:
    """Сопоставляет каждый этап плана с видом работ из правил.

    Один и тот же набор правил не выдаётся двум этапам: если название подошло
    дважды, второй этап остаётся без правил, иначе техника одного этапа
    подтверждала бы другой.
    """
    taken: set[str] = set()
    matched: list[str | None] = []
    for title in titles:
        available = {work_id: known for work_id, known in known_titles.items() if work_id not in taken}
        work_id = match_work_id(title, available)
        if work_id is not None:
            taken.add(work_id)
        matched.append(work_id)
    return tuple(matched)
