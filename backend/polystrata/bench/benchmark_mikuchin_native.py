"""Reproducible Windows old/new strata-poly inference comparison.

Runs one native engine at a time with the *same* model/configuration and
a cloned expert profile. Does not touch the running Mikuchin server, service
configuration, images, user chats, or on-disk KV session files.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "serve"), str(ROOT)]
from strata_tokenizer import Tokenizer  # noqa: E402

DEFAULT_CONFIG = ROOT.parent.parent / "config" / "active.json"
DEFAULT_CANDIDATE = Path(r"E:\mikuchin-native-review-20261113-2\Release\strata-poly.exe")


def gpu_snapshot() -> dict:
    cp = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
         "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    if cp.returncode:
        return {}
    try:
        vals = [int(v.strip()) for v in cp.stdout.splitlines()[0].split(",")]
        return dict(used_mib=vals[0], free_mib=vals[1], util_pct=vals[2])
    except (ValueError, IndexError):
        return {}


def other_native_running() -> list:
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='strata-poly.exe'\" | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15)
        return [int(x.strip()) for x in cp.stdout.splitlines() if x.strip().isdigit()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def prepare_tokens(tokenizer: Tokenizer) -> dict[str, list[int]]:
    """Constant prompt ID sequences across both native executables."""
    intro = tokenizer.encode("<start_of_turn>user\n", parse_special=True)
    outro = tokenizer.encode("\n<end_of_turn>\n<start_of_turn>model\n", parse_special=True)
    base = ("Design an efficient local large-language-model assistant on a workstation "
            "with 8 GB GPU VRAM and 64 GB RAM. Compare GPU expert caches, CPU dispatch, "
            "prefill and token decoding. Explain tradeoffs with concrete examples. ")
    unit = tokenizer.encode(base * 160, parse_special=False)

    def prompt(n: int, prefix: str) -> list[int]:
        head = tokenizer.encode(prefix + "\n", parse_special=False)
        span = max(n - len(intro) - len(outro) - len(head), 0)
        return intro + head + unit[:span] + outro

    # The turn-2 / turn-3 contexts *extend* the previous, byte-identical
    # prompt IDs so that the model's conversation cache has real prefix reuse.
    turn1 = prompt(512, "Let's work through a CPU/GPU inference design.")
    user2 = tokenizer.encode(
        "The next user turn asks for a cache eviction strategy.\n"
        "<end_of_turn>\n<start_of_turn>user\n"
        "Propose a cache eviction strategy for the same hardware.\n"
        "<end_of_turn>\n<start_of_turn>model\n", parse_special=True)
    user3 = tokenizer.encode(
        "Now show how to test this cache strategy.\n"
        "<end_of_turn>\n<start_of_turn>user\n"
        "Which metrics would demonstrate robust real-time behavior?\n"
        "<end_of_turn>\n<start_of_turn>model\n", parse_special=True)
    turn2 = turn1 + user2
    turn3 = turn2 + user3
    return {
        "warmup_128": prompt(128, "Say one short thing about local inference."),
        "short_384": prompt(384, "Summarize the performance considerations."),
        "medium_1536": prompt(1536, "Describe a concrete deployment."),
        "long_4096": prompt(4096, "Give a thorough, structured performance review."),
        "turn1": turn1,
        "turn2": turn2,
        "turn3": turn3,
    }


def prepare_interleaved_tokens(tokenizer: Tokenizer) -> dict[str, list[int]]:
    """Two concurrent logical chats alternating on the same engine.

    First turns exceed the 1,024-token minimum to exercise the native
    conversation-park path instead of only the immediate sequence prefix.
    Both executable variants receive identical fixed prompt tokens.
    """
    start = tokenizer.encode("<start_of_turn>user\n", parse_special=True)
    end = tokenizer.encode("\n<end_of_turn>\n<start_of_turn>model\n", parse_special=True)
    sentence = ("Local models route experts between a CUDA GPU cache and CPU workers. "
                "The model must reason about throughput, GPU headroom, and RAM cache efficiency. ")
    filler = tokenizer.encode(sentence * 140, parse_special=False)

    def base(topic):
        head = tokenizer.encode(topic + "\n", parse_special=False)
        return start + head + filler[:1400 - len(start) - len(head) - len(end)] + end

    def next_turn(previous, text):
        return (previous + tokenizer.encode(
            "The previous assistant answered with a deterministic test plan.\n"
            "<end_of_turn>\n<start_of_turn>user\n" + text +
            "\n<end_of_turn>\n<start_of_turn>model\n", parse_special=True))

    a1 = base("Conversation A: describe efficient local GPU offloading.")
    b1 = base("Conversation B: describe power-efficient CPU workloads.")
    a2 = next_turn(a1, "How should I allocate GPU and CPU expert capacity?")
    b2 = next_turn(b1, "How would I measure power and latency for CPU experts?")
    a3 = next_turn(a2, "Explain what happens when another CUDA process starts.")
    b3 = next_turn(b2, "Explain how to preserve foreground app responsiveness.")
    a4 = next_turn(a3, "Give a concise final deployment checklist.")
    b4 = next_turn(b3, "Give a concise final benchmark checklist.")
    return {"chat_A1": a1, "chat_B1": b1, "chat_A2": a2, "chat_B2": b2,
            "chat_A3": a3, "chat_B3": b3, "chat_A4": a4, "chat_B4": b4}


class Native:
    def __init__(self, label: str, exe: Path, cfg: dict, profile: Path, out: Path,
                 freeze_experts: bool = True):
        self.label, self.exe, self.cfg, self.profile = label, exe, cfg, profile
        self.freeze_experts = freeze_experts
        self.output = out
        self.proc = None
        self.lines = queue.Queue()
        self.stderr_lines = collections.deque(maxlen=80)
        self.info = {}
        self.gpu_samples = []
        self.stop_monitor = threading.Event()
        self.load_s = None
        self.before_gpu = gpu_snapshot()

    def start(self):
        args = list(self.cfg["args"])
        if "--expert-profile" in args:
            args[args.index("--expert-profile") + 1] = str(self.profile)
        else:
            args += ["--expert-profile", str(self.profile)]
        args.append("--serve")
        env = os.environ.copy()
        dirs = [str(Path(x)) for x in self.cfg.get("lib_dirs", []) if Path(x).is_dir()]
        env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
        # Fix freeze modes, if inherited, so both runs agree on the environment.
        if self.freeze_experts:
            env["STRATA_FREEZE_EXPERTS"] = "1"
        else:
            env.pop("STRATA_FREEZE_EXPERTS", None)
        env.pop("STRATA_ROUTE_TAIL_SKIP", None)
        env.pop("CUDA_VISIBLE_DEVICES", None)
        env["CUDA_VISIBLE_DEVICES"] = str(self.cfg.get("gpu", 0))
        command = [str(self.exe)] + args
        print(f"Starting {self.label}: {self.exe.name} / model {Path(args[args.index('--model')+1]).name}", flush=True)
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / f"{self.label}_command.json").write_text(
            json.dumps(dict(exe=str(self.exe), args=args,
                            env=dict(CUDA_VISIBLE_DEVICES=env["CUDA_VISIBLE_DEVICES"],
                                     STRATA_FREEZE_EXPERTS=env.get("STRATA_FREEZE_EXPERTS"))),
                       indent=2), encoding="utf-8")
        self.stderr_file = (self.output / f"{self.label}_stderr.log").open("w", encoding="utf-8")
        begin = time.perf_counter()
        self.proc = subprocess.Popen(
            command, cwd=self.cfg.get("cwd") or str(ROOT), env=env,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def pump_stdout():
            try:
                for line in self.proc.stdout:
                    self.lines.put(line.strip())
            finally:
                self.lines.put(None)
        def pump_stderr():
            for line in self.proc.stderr:
                self.stderr_lines.append(line.strip())
                self.stderr_file.write(line)
                self.stderr_file.flush()
        threading.Thread(target=pump_stdout, daemon=True).start()
        threading.Thread(target=pump_stderr, daemon=True).start()
        def gpu_monitor():
            try:
                import psutil
                ps = psutil.Process(self.proc.pid)
            except Exception:
                ps = None
            while not self.stop_monitor.is_set():
                snap = gpu_snapshot()
                snap["monotonic_s"] = round(time.perf_counter() - begin, 1)
                if ps:
                    try:
                        snap["process_rss_mib"] = round(ps.memory_info().rss / 1048576)
                    except Exception:
                        pass
                self.gpu_samples.append(snap)
                self.stop_monitor.wait(1.5)
        threading.Thread(target=gpu_monitor, daemon=True).start()
        while True:
            line = self.next_line(timeout=180)
            if line.startswith("INFO "):
                self.info.update(dict(kv.split("=", 1) for kv in line.split()[1:] if "=" in kv))
            elif line.startswith("READY "):
                self.load_s = round(time.perf_counter() - begin, 3)
                print(f"{self.label} READY in {self.load_s}s, workers={self.info.get('pool_workers')}, "
                      f"GPU free={gpu_snapshot().get('free_mib', '?')} MiB", flush=True)
                return
            elif line.startswith("ERR "):
                raise RuntimeError(f"Native engine failed to load: {line}")

    def next_line(self, timeout=180) -> str:
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"{self.label} produced no protocol line in {timeout}s; "
                               f"stderr={list(self.stderr_lines)[-6:]}") from None
        if line is None:
            raise RuntimeError(f"{self.label} exited unexpectedly code={self.proc.poll()}; "
                               f"stderr={list(self.stderr_lines)[-8:]}")
        return line

    def send(self, line: str):
        if self.proc.poll() is not None:
            raise RuntimeError(f"{self.label} is not running")
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def budget(self) -> dict:
        if self.info.get("budget_query") != "1":
            return {"supported": False}
        self.send("BUDGET")
        while True:
            line = self.next_line(15)
            if line.startswith("BUDGET "):
                return dict(kv.split("=", 1) for kv in line.split()[1:] if "=" in kv)
            if line.startswith("ERR"):
                return {"error": line}

    def generate(self, name: str, ids: list[int], max_new: int = 40,
                 image_file: Path | None = None, image_pad: int | None = None) -> dict:
        start = time.perf_counter()
        if image_file is not None:
            if image_pad is None or " " in str(image_file) or not image_file.is_file():
                raise ValueError("GENI needs an existing no-space embedding path and image_pad")
            request = f"GENI {max_new} temperature=0 seed=42 image_pad={image_pad} {image_file} "
        else:
            request = f"GEN {max_new} temperature=0 seed=42 "
        self.send(request + ",".join(map(str, ids)))
        sampled = []
        progress = []
        first_token_s = None
        while True:
            line = self.next_line(360)
            if line.startswith("T "):
                sampled.append(int(line.split()[1]))
                if first_token_s is None:
                    first_token_s = time.perf_counter() - start
            elif line.startswith(("PP ", "RESUME ", "P ", "YIELD ")):
                if len(progress) < 8:
                    progress.append(line)
            elif line.startswith("DONE "):
                cols = line.split()
                r = {
                    "case": name,
                    "input_token_count": len(ids),
                    "max_new": max_new,
                    "generated_count": int(cols[1]),
                    "prompt_count": int(cols[2]),
                    "prompt_ms": float(cols[3]),
                    "decode_ms": float(cols[4]),
                    "finish": cols[5],
                    "reused_count": int(cols[8]) if len(cols) >= 9 else None,
                    "read_count": int(cols[14]) if len(cols) >= 15 else None,
                    "gpu_expert_hits": int(cols[9]) if len(cols) >= 10 else None,
                    "expert_lookups": int(cols[10]) if len(cols) >= 11 else None,
                    "prefill_tps": round(
                        (int(cols[14]) if len(cols) >= 15 else len(ids)) / (float(cols[3]) / 1000), 3)
                        if float(cols[3]) > 0 else None,
                    "decode_tps": round(int(cols[1]) / (float(cols[4]) / 1000), 3)
                        if float(cols[4]) > 0 else None,
                    "first_token_wall_s": round(first_token_s, 3) if first_token_s else None,
                    "wall_s": round(time.perf_counter() - start, 3),
                    "tokens": sampled,
                    "progress": progress,
                    "image_rows": sum(1 for item in ids if item == image_pad) if image_file else 0,
                }
                print(f"{self.label} {name}: {len(ids)} in, {r['generated_count']} out, "
                      f"prefill={r['prefill_tps']} tok/s decode={r['decode_tps']} tok/s "
                      f"reused={r['reused_count']} wall={r['wall_s']}s", flush=True)
                return r
            elif line.startswith(("ERR ", "FATAL")):
                raise RuntimeError(f"{self.label} {name}: {line}")

    def close(self):
        self.stop_monitor.set()
        if self.proc:
            try:
                if self.proc.poll() is None:
                    self.send("QUIT")
                    self.proc.wait(timeout=20)
            except Exception:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=12)
                except Exception:
                    pass
        if hasattr(self, "stderr_file"):
            self.stderr_file.close()


def save(data: dict, path: Path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--only", choices=("baseline", "candidate", "both"), default="both")
    ap.add_argument("--threads", type=int, default=None,
                    help="Force same CPU expert thread count for both executables; omit for desktop auto policy")
    ap.add_argument("--stress-only", action="store_true",
                    help="Alternate two logical conversations to test parked KV cache and stability")
    ap.add_argument("--unfrozen", action="store_true",
                    help="Production-style adaptive expert cache (default is frozen for parity testing)")
    args = ap.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    old = Path(cfg["exe"])
    new = args.candidate
    for path in (old, new, Path(cfg["args"][cfg["args"].index("--model") + 1])):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=True)
    original_profile = Path(cfg["args"][cfg["args"].index("--expert-profile") + 1])
    tokenizer = Tokenizer.from_dir(Path(cfg["tokenizer"]))
    prompts = prepare_interleaved_tokens(tokenizer) if args.stress_only else prepare_tokens(tokenizer)
    if not args.stress_only:
        assert len(prompts["long_4096"]) == 4096
    if args.threads is not None:
        assert 1 <= args.threads <= 256
        if "--threads" in cfg["args"]:
            cfg["args"][cfg["args"].index("--threads") + 1] = str(args.threads)
        else:
            cfg["args"] += ["--threads", str(args.threads)]
    labels = (["baseline", "candidate"] if args.only == "both"
              else [args.only])
    results = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config": str(args.config),
        "model": cfg["args"][cfg["args"].index("--model") + 1],
        "labels": labels,
        "thread_policy": args.threads or "auto",
        "stress_only": args.stress_only,
        "freeze_experts": not args.unfrozen,
        "input_case_lengths": {name: len(ids) for name, ids in prompts.items()},
        "runs": {},
    }
    result_file = args.output / "results.json"
    for label in labels:
        if other_native_running():
            raise RuntimeError("Another live strata-poly.exe process exists; benchmark aborted")
        pre = gpu_snapshot()
        if pre.get("used_mib", 8192) > 1400 or pre.get("free_mib", 0) < 6000:
            raise RuntimeError(f"GPU not idle before {label}: {pre}; aborting without touching the service")
        test_profile = args.output / f"{label}_expert-profile.txt"
        if original_profile.exists():
            shutil.copyfile(original_profile, test_profile)
        exe = old if label == "baseline" else new
        native = Native(label, exe, cfg, test_profile, args.output,
                        freeze_experts=not args.unfrozen)
        summary = {"exe": str(exe), "sha256": None, "cases": [], "gpu_before": pre}
        results["runs"][label] = summary
        save(results, result_file)
        try:
            native.start()
            summary["info"] = native.info
            summary["load_s"] = native.load_s
            summary["budget_before"] = native.budget()
            for case, ids in prompts.items():
                if args.stress_only:
                    max_new = 16
                elif case == "warmup_128":
                    max_new = 8
                else:
                    max_new = 32 if case.startswith("turn") else 40
                out = native.generate(case, ids, max_new=max_new)
                summary["cases"].append(out)
                save(results, result_file)
            summary["budget_after"] = native.budget()
            summary["status"] = "complete"
        except BaseException as e:
            summary["status"] = "error"
            summary["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            raise
        finally:
            native.close()
            summary["returncode"] = native.proc.returncode if native.proc else None
            summary["gpu_samples"] = native.gpu_samples
            summary["gpu_peak_mib"] = max(
                (s.get("used_mib", 0) for s in native.gpu_samples), default=None)
            summary["process_rss_peak_mib"] = max(
                (s.get("process_rss_mib", 0) for s in native.gpu_samples), default=None)
            summary["gpu_after"] = gpu_snapshot()
            summary["stderr_tail"] = list(native.stderr_lines)[-14:]
            save(results, result_file)
        time.sleep(4)  # let CUDA/WDDM free the old context before loading the other exe
    if args.only == "both" and all(results["runs"][x]["status"] == "complete" for x in labels):
        a = {x["case"]: x for x in results["runs"]["baseline"]["cases"]}
        b = {x["case"]: x for x in results["runs"]["candidate"]["cases"]}
        results["comparison"] = {}
        for name in a:
            x, y = a[name], b[name]
            results["comparison"][name] = {
                "output_equal": x["tokens"] == y["tokens"],
                "prefill_speed_ratio": round(y["prefill_tps"] / x["prefill_tps"], 3)
                    if x["prefill_tps"] else None,
                "decode_speed_ratio": round(y["decode_tps"] / x["decode_tps"], 3)
                    if x["decode_tps"] else None,
            }
        save(results, result_file)
        print("A/B complete, output:", result_file, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
