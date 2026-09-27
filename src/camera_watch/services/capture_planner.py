"""Расписание съёмки и положение камеры во времени.

Ролик камеры крутится по кругу, и его положение считается от часов сервера. Это нужно не
для красоты: иначе двое смотрящих видели бы разные секунды одной камеры, а снятый по
расписанию кадр не совпадал бы с тем, что в эту минуту показывали онлайн.

Съёмка привязана к границам периода, а не к моменту прошлой съёмки: при периоде в двадцать
минут кадры ложатся на :00, :20 и :40, как и слоты смены в основном сервисе. Иначе после
каждого перезапуска сетка съёмки уезжала бы, и кадры перестали бы попадать в слоты.
"""

from datetime import datetime, timedelta

SECONDS_IN_MINUTE = 60
MIN_PERIOD_MINUTES = 1
# На сколько частей делится ролик при съёмке по расписанию. Нужно из-за демонстрационных
# роликов: они длиной в минуту, а снимаем раз в двадцать минут, и без сдвига каждый
# снимок приходился бы на одну и ту же секунду одной и той же минуты. Это особенность
# демонстрации, а не метода: у настоящей камеры такого совпадения периодов не бывает.
PHASE_STEPS = 3


def position_seconds(moment: datetime, duration_seconds: float) -> float:
    """Секунда ролика, которую камера показывает в этот момент."""
    if duration_seconds <= 0:
        return 0.0
    elapsed = moment.timestamp()
    position = elapsed % duration_seconds
    return position


def capture_position(moment: datetime, duration_seconds: float, period_minutes: int) -> float:
    """Секунда ролика, которую берёт съёмка по расписанию.

    Соседние съёмки идут по ролику с шагом, а не бьют в одну точку: иначе весь архив
    демонстрационной камеры состоял бы из одного и того же кадра.
    """
    if duration_seconds <= 0:
        return 0.0
    period = max(period_minutes, MIN_PERIOD_MINUTES)
    slot_number = int(moment.timestamp() // (period * SECONDS_IN_MINUTE))
    step = duration_seconds / PHASE_STEPS
    position = (slot_number * step) % duration_seconds
    return position


def slot_start(moment: datetime, period_minutes: int) -> datetime:
    """Начало периода съёмки, в который попадает момент."""
    period = max(period_minutes, MIN_PERIOD_MINUTES)
    minute = (moment.minute // period) * period
    start = moment.replace(minute=minute, second=0, microsecond=0)
    return start


def is_due(last_captured_at: datetime | None, moment: datetime, period_minutes: int) -> bool:
    """Пора ли снимать: в текущем периоде кадра ещё нет."""
    if last_captured_at is None:
        return True
    due = last_captured_at < slot_start(moment, period_minutes)
    return due


def next_capture_at(last_captured_at: datetime | None, moment: datetime, period_minutes: int) -> datetime:
    """Когда ожидается следующая съёмка."""
    period = max(period_minutes, MIN_PERIOD_MINUTES)
    if is_due(last_captured_at, moment, period):
        return moment
    following = slot_start(moment, period) + timedelta(minutes=period)
    return following
