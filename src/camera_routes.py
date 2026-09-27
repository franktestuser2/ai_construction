"""HTTP-вход контура наблюдения за камерами.

Отдельный маршрутизатор, а не часть основного входа: контур наблюдения — самостоятельный
сервис, который сегодня живёт в одном процессе с разбором, а завтра может уехать на
площадку. Связь с основным сервисом у него одна — отправка снятых кадров по HTTP.
"""

import logging
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse

from camera_pages import render_camera, render_cameras
from safety_pages import render_safety
from camera_watch.facade import CameraWatchFacade

logger = logging.getLogger(__name__)

CAMERAS_URL = "/cameras"
JPEG_TYPE = "image/jpeg"
MJPEG_TYPE = "multipart/x-mixed-replace; boundary=frame"
BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
STREAM_TAIL = b"\r\n"
# Поток ограничен по времени: вкладку оставляют открытой надолго, а каждый поток
# держит свой декодер. Страница открывает его заново, пока вкладка жива.
STREAM_SECONDS = 240.0
DEFAULT_SIZE = (960, 540)
REDIRECT_CODE = 303
NO_CAMERA_MESSAGE = "Камера не найдена"
NO_PHOTO_MESSAGE = "Снимок не найден"
NO_CLIP_MESSAGE = "Отрезок записи не найден"
NO_FRAME_MESSAGE = "Камера не отдала кадр"
EVENTS_LIMIT = 60


def build_camera_router(watch: CameraWatchFacade, keep_hours: int) -> APIRouter:
    """Собирает маршруты контура наблюдения вокруг его фасада."""
    router = APIRouter()

    @router.get(CAMERAS_URL, response_class=HTMLResponse)
    def cameras_page() -> HTMLResponse:
        """Страница со всеми камерами."""
        states = watch.states(datetime.now())
        page = render_cameras(states, watch.pool(), keep_hours)
        return HTMLResponse(page)

    @router.get("/cameras/{camera_id}", response_class=HTMLResponse)
    def camera_page(camera_id: str) -> HTMLResponse:
        """Страница одной камеры с живым просмотром и архивом."""
        camera = watch.camera(camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail=NO_CAMERA_MESSAGE)
        moment = datetime.now()
        page = render_camera(
            camera,
            watch.frames(camera_id),
            watch.next_capture(camera, moment),
            _size(watch, camera_id),
            keep_hours,
        )
        return HTMLResponse(page)

    @router.get("/cameras/{camera_id}/stream")
    def camera_stream(camera_id: str) -> StreamingResponse:
        """Живой просмотр камеры потоком JPEG."""
        source = watch.source(camera_id)
        if source is None or not source.exists():
            raise HTTPException(status_code=404, detail=NO_CAMERA_MESSAGE)
        start = watch.live_position(camera_id, datetime.now())
        stream = _wrap_multipart(source.stream_jpeg(start, STREAM_SECONDS))
        return StreamingResponse(stream, media_type=MJPEG_TYPE)

    @router.get("/cameras/{camera_id}/frame.jpg")
    def camera_frame(camera_id: str) -> Response:
        """Один кадр камеры — запасной путь, если поток не открылся."""
        content = watch.live_jpeg(camera_id, datetime.now())
        if not content:
            raise HTTPException(status_code=404, detail=NO_FRAME_MESSAGE)
        return Response(content=content, media_type=JPEG_TYPE)

    @router.post("/cameras/{camera_id}/capture")
    def capture_now(camera_id: str) -> RedirectResponse:
        """Снимает кадр немедленно, не дожидаясь расписания."""
        outcome = watch.capture(camera_id, datetime.now())
        if outcome is None:
            raise HTTPException(status_code=404, detail=NO_CAMERA_MESSAGE)
        return RedirectResponse(f"/cameras/{camera_id}", status_code=REDIRECT_CODE)

    @router.post("/cameras/{camera_id}/send")
    def send_frames(camera_id: str) -> RedirectResponse:
        """Передаёт снятое основному сервису."""
        sent, note = watch.send_to_main_service(camera_id)
        logger.info("Камера %s: %s", camera_id, note)
        return RedirectResponse(f"/cameras/{camera_id}", status_code=REDIRECT_CODE)

    @router.get("/cameras/{camera_id}/photos/{name}")
    def camera_photo(camera_id: str, name: str) -> FileResponse:
        """Снимок из архива камеры; имя берётся без пути."""
        target = watch.photo_path(camera_id, name)
        if not target.exists():
            raise HTTPException(status_code=404, detail=NO_PHOTO_MESSAGE)
        return FileResponse(target)

    @router.get("/cameras/{camera_id}/thumbs/{name}")
    def camera_thumb(camera_id: str, name: str) -> FileResponse:
        """Миниатюра снимка для показа пулом."""
        target = watch.thumb_path(camera_id, name)
        if not target.exists():
            raise HTTPException(status_code=404, detail=NO_PHOTO_MESSAGE)
        return FileResponse(target)

    @router.get("/cameras/{camera_id}/clips/{name}")
    def camera_clip(camera_id: str, name: str) -> FileResponse:
        """Отрезок записи к событию."""
        target = watch.clip_path(camera_id, name)
        if not target.exists():
            raise HTTPException(status_code=404, detail=NO_CLIP_MESSAGE)
        return FileResponse(target)

    @router.get("/safety", response_class=HTMLResponse)
    def safety_page() -> HTMLResponse:
        """Лента отметок охраны труда по всем камерам."""
        events = watch.safety_events(EVENTS_LIMIT)
        sizes = {camera.camera_id: _size(watch, camera.camera_id) for camera in watch.cameras()}
        page = render_safety(events, watch.safety_checks(), sizes)
        return HTMLResponse(page)

    return router


def _wrap_multipart(frames: Iterator[bytes]) -> Iterator[bytes]:
    """Оборачивает кадры в поток, который браузер показывает как видео."""
    for content in frames:
        if not content:
            continue
        yield BOUNDARY % len(content) + content + STREAM_TAIL


def _size(watch: CameraWatchFacade, camera_id: str) -> tuple[int, int]:
    """Размер кадра камеры — по нему рамки кладутся поверх снимка."""
    source = watch.source(camera_id)
    if source is None or not source.exists():
        return DEFAULT_SIZE
    info = source.describe()
    size = (info.width or DEFAULT_SIZE[0], info.height or DEFAULT_SIZE[1])
    return size
