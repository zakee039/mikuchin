"""Independent process for paid image calls; never invoked by Gateway threads.

Startup is intentionally conservative: in-flight/queued jobs left from a prior
worker process become failed, never automatically replayed (possible billing).
Start this process BEFORE the Gateway accepts paid image submissions.
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

from .conversations import ConversationStore
from .image_jobs import ImageJobStore

LOG = logging.getLogger("mikuchin.image-worker")


@contextlib.contextmanager
def singleton_lock(path: Path):
    """OS-held lock; a second worker must never reset live billable jobs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0)
        if not f.read(1):
            f.seek(0)
            f.write(b"0")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as e:
                raise RuntimeError("Another native Image Worker already owns this data root") from e
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise RuntimeError("Another native Image Worker already owns this data root") from e
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class ImageWorker:
    def __init__(self, root: str | Path, *, poll: float = 0.35):
        self.root = Path(root).resolve()
        self.store = ImageJobStore(self.root)
        self.poll = poll
        self.stop = threading.Event()

    def run_once(self):
        item = self.store.take_pending()
        if item is None:
            return False
        ident, request = item
        self.store.execute_claimed(ident, request)
        return True

    def run_forever(self):
        with singleton_lock(self.root / "native-worker.lock"):
            self.store.fail_uncertain_on_worker_restart()

            def heartbeat_loop():
                while not self.stop.is_set():
                    try:
                        self.store.heartbeat()
                    except Exception as exc:
                        LOG.error("Worker heartbeat failure: %s",type(exc).__name__)
                    self.stop.wait(0.6)

            heartbeat = threading.Thread(target=heartbeat_loop,daemon=True)
            heartbeat.start()
            LOG.info("Native Image Worker started, PID=%s",os.getpid())
            try:
                while not self.stop.is_set():
                    if not self.run_once():
                        self.stop.wait(self.poll)
            finally:
                self.stop.set()
                heartbeat.join(timeout=3)
                self.store.worker_offline()
                LOG.info("Native Image Worker stopped")


def main():
    parser=argparse.ArgumentParser(description="Isolated Mikuchin online Image Worker")
    parser.add_argument("--data-dir",default=os.environ.get("MIKUCHIN_NATIVE_DATA_DIR") or
                        ConversationStore.default_root())
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    worker=ImageWorker(Path(args.data_dir) / "images")
    for sig in (signal.SIGINT,signal.SIGTERM):
        try: signal.signal(sig,lambda *_: worker.stop.set())
        except (ValueError,OSError): pass
    worker.run_forever()


if __name__ == "__main__":
    main()
