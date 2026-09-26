"""Чтение значений из ответа мультимодальной модели.

В режиме «ответ — объект JSON» провайдер не гарантирует ни типы, ни перечисления:
булево приходит то настоящим `true`, то строкой «да», а статус вместо одного из
четырёх значений — целым предложением «работает — самосвал под погрузкой».
Прямое приведение здесь опасно: непустая строка «false» стала бы истиной,
а неизвестный статус ронял бы разбор всей смены.
"""

import logging

from ..entity import EquipmentStatus

logger = logging.getLogger(__name__)

TRUE_WORDS = frozenset({"true", "да", "yes", "1"})
FALSE_WORDS = frozenset({"false", "нет", "no", "0", ""})


def read_bool(value: object, default: bool = False) -> bool:
    """Приводит значение из ответа модели к булеву, понимая строковую запись."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().casefold()
        if word in TRUE_WORDS:
            return True
        if word in FALSE_WORDS:
            return False
        return default
    if value is None:
        return default
    truthy = bool(value)
    return truthy


def read_status(value: object, default: EquipmentStatus = EquipmentStatus.NOT_APPLICABLE) -> EquipmentStatus:
    """Приводит статус из ответа модели к значению перечисления.

    Модель нередко дописывает к статусу объяснение через тире, поэтому кроме
    точного совпадения проверяется начало строки и вхождение.
    """
    text = str(value).strip().casefold()
    for status in EquipmentStatus:
        if text == status.value:
            return status
    for status in EquipmentStatus:
        if text.startswith(status.value):
            return status
    for status in EquipmentStatus:
        if status.value in text:
            return status
    logger.warning("Статус вне перечисления, взято умолчание: %s", text[:80])
    return default
