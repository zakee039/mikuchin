"""Actual 3-process supervisor tests on ephemeral ports, no paid APIs/models."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from backend.gateway.supervisor import NativeSupervisor
from backend.gateway.image_jobs import ImageJobStore
from backend.gateway.gpu_gate import gpu_turn


ROOT = Path(__file__).resolve().parents[2]


def spare_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SupervisorTest(unittest.TestCase):
    def test_lan_binding_only_applies_to_gateway_not_private_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = NativeSupervisor(
                data_dir=directory, upstream_port=15340, gateway_port=15349,
                api_key="isolated-test-token", lan_access=True)
            self.assertIn("--lan-access", supervisor._args("gateway"))
            self.assertNotIn("--lan-access", supervisor._args("official"))
            self.assertNotIn("--lan-access", supervisor._args("image-worker"))
            supervisor.lan_access = False
            self.assertNotIn("--lan-access", supervisor._args("gateway"))

    def test_crashed_official_restart_waits_for_image_gpu_lease(self):
        """Never load a crashed text engine into an ongoing Qwen/4x turn."""
        class FakeChild:
            def __init__(self, pid, code):
                self.pid = pid
                self.returncode = code
            def poll(self):
                return self.returncode

        with tempfile.TemporaryDirectory() as directory:
            supervisor = NativeSupervisor(
                data_dir=directory, upstream_port=15340, gateway_port=15349,
                api_key="isolated-test-token")
            supervisor.children = {
                "official": FakeChild(111, 1),
                "image-worker": FakeChild(222, None),
                "gateway": FakeChild(333, None),
            }
            started = []
            def restarted(role):
                started.append(role)
                supervisor.stop.set()
            with mock.patch.object(supervisor, "_start_role", side_effect=restarted):
                thread = threading.Thread(target=supervisor._watch, daemon=True)
                try:
                    with gpu_turn(directory, exclusive=True):
                        thread.start()
                        deadline = time.monotonic() + 5
                        state = {}
                        while time.monotonic() < deadline:
                            status_file = Path(directory) / "supervisor-status.json"
                            if status_file.exists():
                                try:
                                    state = json.loads(status_file.read_text("utf-8"))
                                except (OSError, json.JSONDecodeError):
                                    state = {}
                                if state.get("phase") == "waiting-for-gpu":
                                    break
                            time.sleep(.1)
                        self.assertEqual(started, [])
                        self.assertEqual(state.get("phase"), "waiting-for-gpu")
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(started, ["official"])
                    self.assertEqual(supervisor.child_restarts["official"], 1)
                finally:
                    supervisor.stop.set()
                    thread.join(timeout=4)

    def test_recovery_blocks_in_flight_native_turn_and_active_inference(self):
        from backend.gateway.chat_turns import ChatTurnStore
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            supervisor = NativeSupervisor(data_dir=data, api_key="isolated-test-token")
            store = ImageJobStore(data / "images")
            turns = ChatTurnStore(data)
            # New Worker status file is independent of the jobs SQLite WAL.
            supervisor.launch_times["image-worker"] = time.time() - .2
            report = {"pid": 123, "started_at": time.time(), "updated": time.time(),
                      "active": 0, "stopped": False}
            (data / "images" / "native-worker-health.json").write_text(json.dumps(report))
            self.assertFalse(supervisor._safe_to_recover(
                {"active_inference_requests": 1})[0])
            with turns._db() as db:
                db.execute("""INSERT INTO turns(turn_id,session_id,state,request_json,created,updated)
                    VALUES(?,?,?,?,?,?)""",("a" * 32, "b" * 32,"running","{}",time.time(),time.time()))
            self.assertEqual(supervisor._safe_to_recover(
                {"active_inference_requests": 0}), (False, "native-turn-active"))
            with turns._db() as db:
                db.execute("UPDATE turns SET state='text_done' WHERE turn_id=?", ("a" * 32,))
            self.assertTrue(supervisor._safe_to_recover(
                {"active_inference_requests": 0})[0])

    def test_live_degraded_gateway_recovers_without_restarting_official(self):
        """Real local mock subprocesses: simulate a stuck-but-alive health API."""
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            upstream, gateway = spare_port(), spare_port()
            while upstream == gateway: gateway = spare_port()
            supervisor = NativeSupervisor(data_dir=data, api_key="isolated-test-token",
                                          upstream_port=upstream, gateway_port=gateway,
                                          python=sys.executable, startup_timeout=20)
            normal_probe = supervisor._service_problem
            def simulated_failure():
                if not supervisor.child_restarts["gateway"]:
                    return "degraded:image_job_store", {"active_inference_requests": 0}
                return normal_probe()
            supervisor._service_problem = simulated_failure
            failures = []
            def run():
                try: supervisor.run()
                except Exception as exc: failures.append(repr(exc))
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            try:
                started = None
                deadline = time.monotonic() + 26
                while time.monotonic() < deadline:
                    try:
                        status = json.loads(supervisor.status_file.read_text("utf-8"))
                    except (OSError, ValueError):
                        time.sleep(.1); continue
                    if status.get("phase") == "running" and len(status.get("children",{})) == 3:
                        started = status; break
                    time.sleep(.1)
                self.assertIsNotNone(started, failures)
                official_pid = started["children"]["official"]
                old_gateway = started["children"]["gateway"]
                old_worker = started["children"]["image-worker"]
                deadline = time.monotonic() + 28
                recovered = None
                while time.monotonic() < deadline:
                    try: status = json.loads(supervisor.status_file.read_text("utf-8"))
                    except (OSError, ValueError):
                        time.sleep(.2); continue
                    if (status.get("phase") == "running" and
                            (status.get("last_recovery") or {}).get("role") == "api-stack-health"):
                        recovered = status; break
                    time.sleep(.2)
                self.assertIsNotNone(recovered, failures)
                self.assertEqual(recovered["children"]["official"], official_pid)
                self.assertNotEqual(recovered["children"]["gateway"], old_gateway)
                self.assertNotEqual(recovered["children"]["image-worker"], old_worker)
                result = normal_probe()
                self.assertEqual(result[0], "", result)
                self.assertEqual(supervisor.child_restarts["gateway"], 1)
                self.assertEqual(supervisor.child_restarts["image-worker"], 1)
                self.assertEqual(supervisor.child_restarts["official"], 0)
            finally:
                supervisor.stop.set()
                thread.join(timeout=28)
                self.assertFalse(thread.is_alive(), "Safe stop failed")
            self.assertEqual(failures, [])

    def test_rejects_stable_port_and_stable_data(self):
        with tempfile.TemporaryDirectory() as d:
            for port in (25239,):
                with self.assertRaisesRegex(ValueError,"25239"):
                    NativeSupervisor(data_dir=d,gateway_port=port,api_key="isolated-test-token")
            with self.assertRaisesRegex(ValueError,"stable Mikuchin"):
                NativeSupervisor(data_dir=ROOT.parent/"mikuchin-old"/"chat",api_key="isolated-test-token")
            # The production data directory is now nested inside the Native
            # source tree, not inside the archived old-mixed deployment.
            accepted = NativeSupervisor(data_dir=ROOT/"runtime"/"launcher-user-data",
                                        api_key="isolated-test-token")
            self.assertEqual(accepted.data_dir, ROOT/"runtime"/"launcher-user-data")

    def test_occupied_port_fails_closed_without_touching_listener(self):
        with tempfile.TemporaryDirectory() as d, socket.socket() as listener:
            listener.bind(("127.0.0.1",0))
            listener.listen(1)
            port=listener.getsockname()[1]
            supervisor=NativeSupervisor(data_dir=d,upstream_port=port,
                                        gateway_port=spare_port(),api_key="isolated-test-token")
            with self.assertRaisesRegex(RuntimeError,"already in use"):
                supervisor.run()
            with socket.socket() as probe:
                self.assertEqual(probe.connect_ex(("127.0.0.1",port)),0)

    def test_mock_stack_supervision_and_graceful_stop(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            upstream = spare_port()
            gateway = spare_port()
            while upstream == gateway or gateway == 15239:
                gateway = spare_port()
            key = "TEST_NATIVE_PUBLIC_KEY_12345678"
            env = dict(os.environ, MIKUCHIN_GATEWAY_API_KEY=key, PYTHONDONTWRITEBYTECODE="1")
            supervisor_log = data / "supervisor-test.log"
            logfile = supervisor_log.open("w", encoding="utf-8")
            proc = subprocess.Popen([
                sys.executable,"-u","-B","-m","backend.gateway.supervisor",
                "--engine","mock","--data-dir",str(data),
                "--gateway-port",str(gateway),"--upstream-port",str(upstream),
                "--startup-timeout","20","--control-stdin"],cwd=ROOT,env=env,
                stdin=subprocess.PIPE,stdout=logfile,
                stderr=subprocess.STDOUT,text=True)
            initial = None
            try:
                deadline = time.monotonic()+28
                while time.monotonic() < deadline:
                    self.assertIsNone(proc.poll(),"Supervisor exited during startup: " +
                                      supervisor_log.read_text("utf-8",errors="replace")[-2500:])
                    p=data/"supervisor-status.json"
                    if p.exists():
                        try:initial=json.loads(p.read_text("utf-8"))
                        except (OSError,json.JSONDecodeError): pass
                        if initial and initial.get("phase")=="running":break
                    time.sleep(.1)
                self.assertIsNotNone(initial)
                self.assertEqual(initial["phase"],"running")
                self.assertEqual(set(initial["children"]),{"official","gateway","image-worker"})
                headers={"Authorization":"Bearer "+key}
                with urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{gateway}/health",headers=headers),timeout=6) as r:
                    health=json.load(r)
                self.assertEqual(health["status"],"ok")
                self.assertTrue(health["image_worker_ready"])
                self.assertTrue(health["official_polystrata_reachable"])
                # Never expose the locally generated upstream private token.
                self.assertNotIn("STRATA_API_KEY",json.dumps(initial))
                self.assertNotIn(key,json.dumps(initial))
                self.assertEqual(proc.poll(),None)

                # Crash only the disposable test Worker; supervised restart
                # must restore the heartbeat and publish a different PID.
                old = initial["children"]["image-worker"]
                # uv-managed Windows venvs can use a Python executable
                # redirector. The heartbeat records the actual interpreter
                # PID, whereas Popen.pid may name its parent redirector.
                os.kill(ImageJobStore(data / "images").worker_pid(),signal.SIGTERM)
                deadline=time.monotonic()+15
                restarted=False
                while time.monotonic()<deadline:
                    p=data/"supervisor-status.json"
                    try:now=json.loads(p.read_text("utf-8"))
                    except (OSError,json.JSONDecodeError):now={}
                    if (now.get("phase")=="running" and
                            now.get("children",{}).get("image-worker") not in (None,old)):
                        restarted=True
                        break
                    time.sleep(.2)
                self.assertTrue(restarted,"Worker did not restart after an unexpected exit")
                self.assertIsNone(proc.poll())
                self.assertGreaterEqual(now.get("child_restarts", {}).get("image-worker", 0), 1)
                self.assertEqual(now.get("last_recovery", {}).get("role"), "image-worker")
                with urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{gateway}/health",headers=headers),timeout=5) as r:
                    self.assertTrue(json.load(r)["image_worker_ready"])
            finally:
                if proc.poll() is None and proc.stdin:
                    try:
                        proc.stdin.write("STOP\n")
                        proc.stdin.flush()
                        proc.wait(timeout=20)
                    except (BrokenPipeError,subprocess.TimeoutExpired):
                        proc.kill()
                        proc.wait(timeout=6)
                    finally:proc.stdin.close()
                logfile.close()
            self.assertEqual(proc.returncode,0)
            finished=json.loads((data/"supervisor-status.json").read_text("utf-8"))
            self.assertEqual(finished["phase"],"stopped")
            for port in (gateway,upstream):
                with socket.socket() as s:
                    self.assertNotEqual(s.connect_ex(("127.0.0.1",port)),0)


if __name__=="__main__":
    unittest.main()
