"""Хранение прогонов сервиса на диске.

Каждый прогон — это каталог с тем, что загрузил пользователь, состоянием разбора
и собранным отчётом. Состояние лежит файлом, а не в памяти процесса: перезапуск
сервиса не должен терять уже посчитанное.
"""

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

STATE_FILE_NAME = "state.json"
PLAN_DIR_NAME = "plan"
PHOTOS_DIR_NAME = "photos"
REPORT_FILE_NAME = "report.html"
TIME_FORMAT = "%d.%m.%Y %H:%M"
RUN_ID_LENGTH = 12
STATUS_ACCEPTED = "принят"
STATUS_RUNNING = "разбирается"
STATUS_DONE = "готов"
STATUS_FAILED = "ошибка"


@dataclass
class RunState:
    """Состояние одного прогона: что загружено, что посчитано, чем кончилось."""

    run_id: str
    created_at: str
    status: str = STATUS_ACCEPTED
    stage_title: str = ""
    done_frames: int = 0
    total_frames: int = 0
    stages_total: int = 0
    plan_file: str = ""
    photo_count: int = 0
    binding: str = ""
    error: str = ""
    works: list[dict[str, object]] = field(default_factory=list)

    @property
    def percent(self) -> int:
        """Доля разобранных кадров в процентах."""
        if self.total_frames == 0:
            return 0
        share = round(100 * self.done_frames / self.total_frames)
        return share


class RunStorage:
    """Адаптер работы с каталогами прогонов."""

    def __init__(self, runs_path: Path) -> None:
        self._runs_path = runs_path

    def create(self) -> RunState:
        """Заводит новый прогон и возвращает его начальное состояние."""
        run_id = uuid4().hex[:RUN_ID_LENGTH]
        directory = self._runs_path / run_id
        (directory / PLAN_DIR_NAME).mkdir(parents=True, exist_ok=True)
        (directory / PHOTOS_DIR_NAME).mkdir(parents=True, exist_ok=True)
        state = RunState(run_id=run_id, created_at=datetime.now().strftime(TIME_FORMAT))
        self.save(state)
        logger.info("Заведён прогон %s", run_id)
        return state

    def directory(self, run_id: str) -> Path:
        """Каталог прогона."""
        path = self._runs_path / run_id
        return path

    def plan_dir(self, run_id: str) -> Path:
        """Каталог с загруженным планом."""
        path = self.directory(run_id) / PLAN_DIR_NAME
        return path

    def photos_dir(self, run_id: str) -> Path:
        """Каталог с загруженными снимками."""
        path = self.directory(run_id) / PHOTOS_DIR_NAME
        return path

    def report_path(self, run_id: str) -> Path:
        """Путь собранного отчёта."""
        path = self.directory(run_id) / REPORT_FILE_NAME
        return path

    def save_upload(self, target: Path, content: bytes) -> None:
        """Кладёт загруженный файл на диск."""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def save(self, state: RunState) -> None:
        """Записывает состояние прогона."""
        path = self.directory(state.run_id) / STATE_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, run_id: str) -> RunState | None:
        """Читает состояние прогона, если он существует."""
        path = self.directory(run_id) / STATE_FILE_NAME
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        state = RunState(**payload)
        return state

    def list_runs(self) -> tuple[RunState, ...]:
        """Возвращает прогоны от новых к старым."""
        if not self._runs_path.exists():
            return ()
        states = [self.load(item.name) for item in self._runs_path.iterdir() if item.is_dir()]
        found = [state for state in states if state is not None]
        found.sort(key=lambda state: state.created_at, reverse=True)
        return tuple(found)

    def remove(self, run_id: str) -> None:
        """Удаляет каталог прогона целиком."""
        shutil.rmtree(self.directory(run_id), ignore_errors=True)
