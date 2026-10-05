import logging
import time

from app import jobs, maintenance, notifications
from app.db import SessionLocal

TICK_SECONDS = 60
MAINTENANCE_SECONDS = 60 * 60


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger(__name__).info("worker started")
    last_tick = 0.0
    last_maintenance = 0.0
    while True:
        with SessionLocal() as db:
            worked = jobs.run_one(db) or jobs.run_outbox_one(db)
            if time.monotonic() - last_tick >= TICK_SECONDS:
                notifications.tick(db)
                last_tick = time.monotonic()
            if time.monotonic() - last_maintenance >= MAINTENANCE_SECONDS:
                maintenance.tick(db)
                last_maintenance = time.monotonic()
        if not worked:
            time.sleep(2)


if __name__ == "__main__":
    main()
