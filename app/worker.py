import logging
import signal
import time

from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
running = True


def handle_shutdown(signum, frame) -> None:
    global running
    running = False


def main() -> None:
    settings = get_settings()
    settings.validate_provider_config()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info(
        "phase 1 worker placeholder started",
        extra={"worker_id": settings.worker_id, "upload_dir": str(settings.upload_dir)},
    )
    while running:
        time.sleep(max(settings.worker_poll_interval_seconds, 0.1))
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
