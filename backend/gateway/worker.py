"""Independent process for paid image calls; never invoked by Gateway threads.

Startup is intentionally conservative: in-flight/queued jobs left from a prior
worker process become failed, never automatically replayed (possible billing).
Start this process BEFORE the Gateway accepts paid image submissions.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import signal
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .conversations import ConversationStore
from .image_jobs import ImageJobStore
from . import image_providers

LOG = logging.getLogger("mikuchin.image-worker")
MAX_API_INFLIGHT = 20


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
        # Filesystem heartbeat survives an SQLite WAL locking failure.
        # It contains NO job IDs, prompts, keys or provider request data.
        self.health_path = self.root / "native-worker-health.json"
        self._health_lock = threading.Lock()
        self._boot_at = time.time()
        self._active_count = 0
        self._poll_errors = 0
        self._heartbeat_errors = 0

    def _publish_health(self, *, stopped=False):
        with self._health_lock:
            state = {"pid": os.getpid(), "started_at": self._boot_at,
                     "updated": time.time(), "active": self._active_count,
                     "poll_errors": self._poll_errors,
                     "heartbeat_errors": self._heartbeat_errors,
                     "stopped": stopped}
            self.health_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.health_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state), encoding="utf-8")
            os.replace(temporary, self.health_path)

    def run_once(self):
        """Synchronous helper retained for deterministic tests."""
        item = self.store.take_pending()
        if item is None:
            return False
        ident, request = item
        self.store.execute_claimed(ident, request)
        return True

    @staticmethod
    def _lane(request):
        if request.get("kind")=="upscale":
            return ("local","upscale")
        profile=request.get("strata_image_profile","")
        if isinstance(profile,str) and profile.startswith("local-"):
            return ("local","gpu")
        return ("api",str(profile))

    def _eligible(self,request,active):
        lane,profile=self._lane(request)
        if lane=="local":
            return not any(key[0]=="local" for _,key in active.values())
        api_count=Counter(key for _,key in active.values() if key[0]=="api")
        if sum(api_count.values())>=MAX_API_INFLIGHT:
            return False
        service=image_providers.get(self.store,profile)
        # A deleted service will fail normally when the job is dispatched,
        # but should not stall the entire queue forever.
        configured=service.get("concurrency",1) if service else 1
        limit=min(MAX_API_INFLIGHT,max(1,int(configured)))
        return api_count[("api",profile)] < limit

    @staticmethod
    def _collect_completed(active):
        for future in list(active):
            if not future.done():
                continue
            ident,lane=active.pop(future)
            try:
                future.result()
            except Exception:
                # execute_claimed persists routine provider errors itself.
                # Never replay a possibly billable request after a failure.
                LOG.exception("Uncaught image worker error for job %s",ident)

    def run_forever(self):
        with singleton_lock(self.root / "native-worker.lock"):
            self.store.fail_uncertain_on_worker_restart()

            def heartbeat_loop():
                while not self.stop.is_set():
                    try:
                        self.store.heartbeat()
                        self._heartbeat_errors = 0
                    except Exception as exc:
                        self._heartbeat_errors += 1
                        if self._heartbeat_errors <= 3 or self._heartbeat_errors % 20 == 0:
                            LOG.error("Worker heartbeat failure (%d): %s",
                                      self._heartbeat_errors, type(exc).__name__)
                    self._publish_health()
                    self.stop.wait(0.6)

            heartbeat = threading.Thread(target=heartbeat_loop,daemon=True)
            heartbeat.start()
            LOG.info("Native Image Worker started, PID=%s",os.getpid())
            try:
                # Separate pools ensure a long local GPU job cannot occupy
                # the last API slot, and vice versa. GPU jobs remain strictly
                # serialized, including standalone 4x upscale tasks.
                with (ThreadPoolExecutor(max_workers=MAX_API_INFLIGHT,
                                         thread_name_prefix="native-api-image") as api_pool,
                      ThreadPoolExecutor(max_workers=1,
                                         thread_name_prefix="native-local-image") as local_pool):
                    active={}
                    while not self.stop.is_set():
                        self._collect_completed(active)
                        self._active_count = len(active)
                        try:
                            item=self.store.take_pending(
                                eligible=lambda req:self._eligible(req,active))
                            self._poll_errors = 0
                        except Exception as exc:
                            self._poll_errors += 1
                            if self._poll_errors <= 3 or self._poll_errors % 20 == 0:
                                LOG.error("Native Image Worker queue probe failed (%d): %s",
                                          self._poll_errors, type(exc).__name__)
                            self._publish_health()
                            self.stop.wait(self.poll)
                            continue
                        if item is None:
                            self.stop.wait(self.poll)
                            continue
                        ident,request=item
                        lane=self._lane(request)
                        pool=local_pool if lane[0]=="local" else api_pool
                        future=pool.submit(self.store.execute_claimed,ident,request)
                        active[future]=(ident,lane)
                        self._active_count = len(active)
                        self._publish_health()
                    # On cooperative shutdown, let already-started jobs
                    # finish; never start new provider calls or reissue work.
                    self._collect_completed(active)
            finally:
                self.stop.set()
                heartbeat.join(timeout=3)
                self._active_count = 0
                self._publish_health(stopped=True)
                try:
                    self.store.worker_offline()
                except Exception as exc:
                    LOG.error("Worker offline status update failed: %s",type(exc).__name__)
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
