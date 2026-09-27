"""Передача снятых кадров основному сервису.

Контур наблюдения отдаёт снимки по HTTP, а не кладёт их напрямую в каталоги разбора.
Так сделано потому, что камеры стоят на площадке, а разбор идёт на сервере: сегодня
оба конца живут в одном процессе, но контур не знает об этом ничего, кроме адреса.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

FRAMES_ENDPOINT = "/ingest/frames"
CAMERA_FIELD = "camera_id"
FILES_FIELD = "photos"
JPEG_TYPE = "image/jpeg"
REQUEST_TIMEOUT = 60.0
ACCEPTED_KEY = "accepted"
NOTHING = 0
SEND_FAILED_NOTE = "Основной сервис не принял снимки"


class MainServiceClient:
    """Клиент основного сервиса контроля площадок."""

    def __init__(self, base_url: str, timeout: float = REQUEST_TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def send_frames(self, camera_id: str, files: list[tuple[str, bytes]]) -> tuple[int, str]:
        """Отправляет снимки камеры и возвращает, сколько их принято."""
        payload = [(FILES_FIELD, (name, content, JPEG_TYPE)) for name, content in files]
        try:
            response = httpx.post(
                f"{self._base_url}{FRAMES_ENDPOINT}",
                data={CAMERA_FIELD: camera_id},
                files=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Не удалось передать снимки камеры %s", camera_id)
            return NOTHING, SEND_FAILED_NOTE
        accepted = int(response.json().get(ACCEPTED_KEY, NOTHING))
        note = f"Основной сервис принял снимков: {accepted}"
        return accepted, note
