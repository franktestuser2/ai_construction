"""Сопоставление находок на снимке с позициями правил этапа.

Позиция закрывается любой из своих альтернатив: подачу бетона одинаково
подтверждают миксер, бетононасос и автокран. Правило общее и для суточной
сверки, и для разбора смены по слотам, поэтому живёт отдельно.
"""

from ..entity import ObservedEquipment, PositionAlternative, WorkPosition


def is_same_equipment(alternative: PositionAlternative, observed: ObservedEquipment) -> bool:
    """Проверяет, что находка относится к машине из этой альтернативы.

    Источник находки не важен: одну и ту же машину детектор называет своим английским
    классом, а модель — названием позиции из правил. Экскаватор, опознанный по кадру
    целиком, закрывает позицию так же, как экскаватор, найденный рамкой.
    """
    if observed.machine_type == alternative.machine_type:
        return True
    same = observed.machine_type in alternative.detector_classes
    return same


def match_position(
    position: WorkPosition,
    equipment: tuple[ObservedEquipment, ...],
) -> tuple[ObservedEquipment, ...]:
    """Отбирает находки снимка, которые закрывают позицию любой из альтернатив."""
    matched = []
    for item in equipment:
        if any(is_same_equipment(alternative, item) for alternative in position.alternatives):
            matched.append(item)
    result = tuple(matched)
    return result
