"""Worker entrypoint — jalankan dengan `make worker`."""

import logging
import sys

from ai_asistent_core.config import get_settings
from ai_asistent_core.db import get_rq_connection
from rq import Worker

from worker.jobs import JOBS


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    connection = get_rq_connection()
    worker = Worker(["default"], connection=connection, name="worker-1")
    logging.getLogger("worker.main").info(
        "worker starting jobs=%s", JOBS
    )
    worker.work()


if __name__ == "__main__":
    main()
