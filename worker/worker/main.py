"""Worker entrypoint.

Jalankan dengan: make worker  (dari root project)
"""

import logging
import sys

from redis import Redis
from rq import Worker

from worker.jobs import JOBS
from worker.settings import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    connection = Redis.from_url(settings.redis_url, decode_responses=True)
    worker = Worker(JOBS, connection=connection, name="worker-1")
    logging.getLogger("worker.main").info(
        "worker starting", extra={"queues": [settings.queue_name], "jobs": JOBS}
    )
    worker.work()


if __name__ == "__main__":
    main()
