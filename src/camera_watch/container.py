"""Сборка контура наблюдения за камерами."""

import logging

from camera_watch.adapters.camera_registry_reader import CameraRegistryReader, SafetyChecksReader
from camera_watch.adapters.clip_encoder import ClipEncoder
from camera_watch.adapters.frame_archive import FrameArchive
from camera_watch.adapters.main_service_client import MainServiceClient
from camera_watch.adapters.motion_regions import MotionRegionFinder
from camera_watch.adapters.person_detector import PersonDetector
from camera_watch.entity import DETECTOR_SOURCE, MOTION_SOURCE
from camera_watch.facade import CameraWatchFacade
from camera_watch.services.safety_assessment import SafetyAssessmentService
from config import Settings

logger = logging.getLogger(__name__)


def build_camera_watch(settings: Settings) -> CameraWatchFacade:
    """Собирает контур наблюдения из настроек сервиса."""
    registry = CameraRegistryReader(settings.cameras_path)
    checks_reader = SafetyChecksReader(settings.safety_checks_path)
    encoder = ClipEncoder(
        model_dir=settings.clip_models_path,
        phrase_cache_dir=settings.clip_phrase_cache_path,
        threads=settings.onnx_threads,
    )
    finders = {MOTION_SOURCE: MotionRegionFinder(), DETECTOR_SOURCE: PersonDetector()}
    assessment = SafetyAssessmentService(
        encoder=encoder,
        region_finders=finders,
        checks=checks_reader.read(),
        person_padding=checks_reader.read_padding(),
    )
    archive = FrameArchive(settings.camera_archive_path)
    client = MainServiceClient(settings.main_service_url)
    facade = CameraWatchFacade(
        registry=registry, archive=archive, assessment=assessment, client=client
    )
    return facade
