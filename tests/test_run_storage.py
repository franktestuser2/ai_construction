"""Тесты приёма снимков: отдельными файлами и архивом."""

import zipfile
from io import BytesIO
from pathlib import Path

from site_monitoring.adapters.run_storage import RunStorage

PHOTO_BYTES = b"\xff\xd8\xff\xe0 fake jpeg"


def _archive(names: tuple[str, ...]) -> bytes:
    """Собирает архив с заданными именами внутри."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, PHOTO_BYTES)
    return buffer.getvalue()


def test_отдельный_снимок_кладётся_как_есть(tmp_path: Path) -> None:
    # Arrange
    storage = RunStorage(tmp_path)
    state = storage.create()

    # Act
    saved = storage.save_photos(state.run_id, "кадр.jpg", PHOTO_BYTES)

    # Assert
    assert saved == 1
    assert (storage.photos_dir(state.run_id) / "кадр.jpg").exists()


def test_архив_распаковывается_сервисом(tmp_path: Path) -> None:
    # Arrange
    storage = RunStorage(tmp_path)
    state = storage.create()
    content = _archive(("первый.jpg", "второй.png", "опись.txt"))

    # Act
    saved = storage.save_photos(state.run_id, "снимки.zip", content)

    # Assert: текстовый файл из архива на диск не попадает
    assert saved == 2
    names = sorted(item.name for item in storage.photos_dir(state.run_id).iterdir())
    assert names == ["второй.png", "первый.jpg"]


def test_пути_из_архива_не_повторяются_на_диске(tmp_path: Path) -> None:
    # Arrange: архив с путём наружу каталога прогона
    storage = RunStorage(tmp_path)
    state = storage.create()
    content = _archive(("../../чужой.jpg", "папка/свой.jpg"))

    # Act
    saved = storage.save_photos(state.run_id, "снимки.zip", content)

    # Assert: оба легли рядом по имени файла, наружу ничего не ушло
    assert saved == 2
    names = sorted(item.name for item in storage.photos_dir(state.run_id).iterdir())
    assert names == ["свой.jpg", "чужой.jpg"]


def test_посторонний_файл_снимком_не_считается(tmp_path: Path) -> None:
    # Arrange
    storage = RunStorage(tmp_path)
    state = storage.create()

    # Act
    saved = storage.save_photos(state.run_id, "заметки.txt", PHOTO_BYTES)

    # Assert
    assert saved == 0
