"""Real Gemma4 vision embedding -> mixed image/text native prefill regression.

A single CPU strata-vision encoder produces one SVE file, reused byte-for-byte
by the old and candidate native GPU engines. No Mikuchin server changes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import time

from benchmark_mikuchin_native import (DEFAULT_CANDIDATE, DEFAULT_CONFIG, Native,
                                       gpu_snapshot, other_native_running, save)
from strata_tokenizer import Tokenizer
from serve.server import Vision


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--threads", type=int, default=14)
    args = ap.parse_args()
    if other_native_running() or gpu_snapshot().get("used_mib", 9000) > 1400:
        raise RuntimeError("Native/GPU workload is active: refusing to start vision benchmark")
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if not cfg.get("vision"):
        raise ValueError("The active configuration has no vision encoder")
    for path in [cfg["vision"][key] for key in ("exe", "model", "mmproj")]:
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    from PIL import Image, ImageDraw
    args.output.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (160, 160), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((15, 22, 72, 84), fill=(230, 28, 43))
    draw.ellipse((88, 35, 145, 92), fill=(20, 145, 230))
    draw.polygon(((52, 110), (120, 110), (86, 146)), fill=(42, 164, 58))
    png = args.output / "deterministic_vision_fixture.png"
    img.save(png)
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(
        [p for p in cfg.get("lib_dirs", []) if Path(p).is_dir()] + [env.get("PATH", "")])
    vis_cfg = {**cfg["vision"], "elastic": False}
    tok = Tokenizer.from_dir(Path(cfg["tokenizer"]))
    # Gemma 4 differs from ChatML: the server expands each <|image|>
    # marker to <|image> + N image rows + <image|>.
    image_pad = tok.encode("<|image|>", parse_special=True)
    if len(image_pad) != 1:
        raise ValueError(f"Gemma4 image pad must be one token, got {image_pad}")
    image_pad = image_pad[0]
    report = {"date_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "fixture": str(png), "image_pad": image_pad, "runs": {}}
    results_path = args.output / "results.json"
    log = (args.output / "vision_encoder_stderr.log").open("w", encoding="utf-8")
    vision = None
    try:
        begin = time.perf_counter()
        vision = Vision(vis_cfg, log=log, env=env, lazy=False)
        sve, rows = vision.encode(png.read_bytes())
        report.update(image_embed_s=round(time.perf_counter() - begin, 3),
                      embedding_rows=rows, embedding_bytes=sve.stat().st_size)
        print(f"CPU vision encoded: {rows} rows; {sve.stat().st_size} bytes "
              f"in {report['image_embed_s']}s", flush=True)
        vision.close()  # keep the .sve for the old and candidate native engines

        prefix = tok.encode(
            "<start_of_turn>user\nThis is a technical visual reasoning test. "
            "Describe the relationships among the color-coded geometric shapes. ",
            parse_special=True)
        suffix = tok.encode(
            " The image is a simple diagram, so focus on visible properties. "
            "Please summarize its spatial arrangement.\n"
            "<end_of_turn>\n<start_of_turn>model\n", parse_special=True)
        image_start = tok.encode("<|image>", parse_special=True)
        image_end = tok.encode("<image|>", parse_special=True)
        if len(image_start) != 1 or len(image_end) != 1:
            raise ValueError("Unexpected Gemma4 image delimiters")
        ids = prefix + image_start + [image_pad] * rows + image_end + suffix
        report["input_tokens"] = len(ids)
        print(f"Mixed visual prompt tokens: {len(ids)}", flush=True)
        assert len(ids) < 131072
        save(report, results_path)
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        if "--threads" in config["args"]:
            config["args"][config["args"].index("--threads")+1] = str(args.threads)
        else:
            config["args"] += ["--threads", str(args.threads)]
        profile = Path(cfg["args"][cfg["args"].index("--expert-profile")+1])
        for label, exe in [("baseline", Path(cfg["exe"])),
                           ("candidate", args.candidate)]:
            if other_native_running() or gpu_snapshot().get("used_mib", 9000) > 1400:
                raise RuntimeError(f"Other GPU task active before {label}")
            clone = args.output / (label + "_expert_profile.txt")
            shutil.copyfile(profile, clone)
            runner = Native(label, exe, config, clone, args.output)
            state = {"status": "in_progress", "cases": []}
            report["runs"][label] = state
            save(report, results_path)
            try:
                runner.start()
                state["load_s"] = runner.load_s
                state["workers"] = runner.info.get("pool_workers")
                state["budget"] = runner.budget()
                for case in ("vision_mixed", "vision_mixed_repeat"):
                    state["cases"].append(runner.generate(
                        case, ids, max_new=16, image_file=sve, image_pad=image_pad))
                    save(report, results_path)
                state["status"] = "complete"
            except Exception as e:
                state.update(status="failed", error=repr(e))
                raise
            finally:
                runner.close()
                state["exitcode"] = runner.proc.returncode if runner.proc else None
                state["gpu_peak_mib"] = max(
                    (s.get("used_mib", 0) for s in runner.gpu_samples), default=None)
                state["rss_peak_mib"] = max(
                    (s.get("process_rss_mib", 0) for s in runner.gpu_samples), default=None)
                state["stderr_tail"] = list(runner.stderr_lines)[-8:]
                save(report, results_path)
            time.sleep(4)
        old, new = report["runs"]["baseline"], report["runs"]["candidate"]
        report["token_parity"] = all(
            x["tokens"] == y["tokens"] for x, y in zip(old["cases"], new["cases"]))
        report["cached_tokens"] = {
            label: [x["reused_count"] for x in report["runs"][label]["cases"]]
            for label in ("baseline", "candidate")}
        save(report, results_path)
        print("Vision parity =", report["token_parity"], "cached =", report["cached_tokens"], flush=True)
        return 0 if report["token_parity"] else 4
    finally:
        if vision:
            vision.shutdown()  # remove only the temp encoder dir this script created
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
