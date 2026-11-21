"""Native-owned local Qwen-Image (sd-cli), LoRA and optional Real-ESRGAN.

All binary/model paths come from a private, administrator-provisioned JSON file
in the isolated Native data root; browser input can select only opaque IDs.
No code imports or edits the upstream PolyStrata submodule. Local executions
hold an exclusive GPU turn and ask the *private* official engine to unload;
new Gateway inference requests are gated until reload is attempted.
"""
from __future__ import annotations

import base64
import contextlib
import http.client
import io
import json
import logging
import os
import random
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

try:
    from .gpu_gate import gpu_turn, publish_state
except ImportError:  # unittest discover imports gateway modules by filename
    from gpu_gate import gpu_turn, publish_state

LOG = logging.getLogger("mikuchin.local-image")
ID = re.compile(r"^local-[a-z0-9-]{2,60}$")
LORA_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
STEM = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
TURBO_SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"
AUTO_ANIME = re.compile(r"anime|manga|miku|初音|二次元|动漫|动画|插画", re.IGNORECASE)
NOT_ANIME = re.compile(r"photorealistic|photo|realistic|写实|摄影|照片|非动漫|非二次元", re.IGNORECASE)


class LocalImageError(RuntimeError):
    pass


def config_path(svc):
    return Path(svc.root) / "config" / "native-local-images.json"


def _settings(svc):
    path = config_path(svc)
    if not path.is_file():
        return {"profiles": [], "loras": [], "upscaler": {}}
    if path.stat().st_size > 100_000 or path.is_symlink():
        raise LocalImageError("invalid private local image configuration")
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise LocalImageError("invalid local image configuration")
    profiles = obj.get("profiles", [])
    loras = obj.get("loras", [])
    upscaler = obj.get("upscaler", {})
    if (not isinstance(profiles, list) or len(profiles) > 12 or
        not isinstance(loras, list) or len(loras) > 30 or
        not isinstance(upscaler, dict)):
        raise LocalImageError("invalid local image model registry")
    return {"profiles": profiles, "loras": loras, "upscaler": upscaler}


def _file(value):
    return isinstance(value, str) and bool(value) and Path(value).is_file()


def _profile_good(p):
    return (isinstance(p, dict) and isinstance(p.get("id"), str) and
            bool(ID.fullmatch(p["id"])) and p.get("family") == "qwen_turbo" and
            all(_file(p.get(k)) for k in ("exe", "diffusion_model", "vae", "llm")) and
            (not p.get("llm_vision") or _file(p["llm_vision"])) and
            isinstance(p.get("args", []), list) and
            all(isinstance(a, str) and len(a) < 180 for a in p.get("args", [])))


def get(svc, ident):
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        return None
    return next((p for p in _settings(svc)["profiles"]
                 if isinstance(p, dict) and p.get("id") == ident), None)


def upscaler_ready(svc):
    cfg = _settings(svc)["upscaler"]
    model = cfg.get("model", "realesrgan-x4plus-anime")
    directory = cfg.get("model_dir")
    return bool(cfg.get("enabled") and _file(cfg.get("exe")) and
                isinstance(directory, str) and
                isinstance(model, str) and STEM.fullmatch(model) and
                _file(str(Path(directory) / (model + ".bin"))) and
                _file(str(Path(directory) / (model + ".param"))))


def catalog(svc):
    cfg = _settings(svc)
    models = []
    ready_upscale = upscaler_ready(svc)
    for p in cfg["profiles"]:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not ID.fullmatch(p["id"]):
            continue
        models.append({
            "id": p["id"], "name": str(p.get("name") or p["id"])[:100],
            "family": "qwen_turbo", "type": "local",
            "available": _profile_good(p), "model": str(p.get("model") or p["id"])[:120],
            "max_side": min(max(int(p.get("max_side", 1024)), 256), 2048),
            "steps": 8, "sizes": "all",
            "reference_mode": "single" if p.get("llm_vision") else "none",
            "negative": False, "seed": True, "supports_steps": True,
            "upscale_available": ready_upscale,
        })
    loras = []
    for item in cfg["loras"]:
        if not isinstance(item, dict):
            continue
        ident, path = item.get("id"), item.get("path")
        if not isinstance(ident, str) or not LORA_ID.fullmatch(ident):
            continue
        loras.append({"id": ident, "name": str(item.get("name") or ident)[:100],
                      "family": "qwen_turbo",
                      "available": _file(path) and str(path).lower().endswith(".safetensors") and
                                   bool(STEM.fullmatch(Path(path).stem))})
    return models, loras


def validate(svc, req):
    profile = get(svc, req["strata_image_profile"])
    if not profile or not _profile_good(profile):
        raise ValueError("selected local Qwen-Image files or executable are unavailable")
    width, height = map(int, req["size"].split("x"))
    max_side = min(max(int(profile.get("max_side", 1024)), 256), 2048)
    if not all(256 <= side <= max_side and side % 32 == 0 for side in (width, height)):
        raise ValueError("local Qwen-Image dimensions must be 256..max_side, divisible by 32")
    if len(req.get("strata_reference_assets", [])) > (1 if profile.get("llm_vision") else 0):
        raise ValueError("this local image model cannot use the requested reference images")
    lora_id = req.get("strata_lora_id", "none")
    if lora_id not in (None, "", "none"):
        if not isinstance(lora_id, str) or not LORA_ID.fullmatch(lora_id):
            raise ValueError("invalid local LoRA id")
        match = next((i for i in _settings(svc)["loras"]
                      if isinstance(i, dict) and i.get("id") == lora_id), None)
        if not match or not _file(match.get("path")) or not STEM.fullmatch(Path(match["path"]).stem):
            raise ValueError("selected local LoRA is missing")
        # sd-cli's LoRA model dir is server-owned; the request never supplies a path.
        if Path(match["path"]).suffix.lower() != ".safetensors":
            raise ValueError("LoRA must be a safetensors file")
    if req.get("strata_upscale") == "4x":
        if not upscaler_ready(svc):
            raise ValueError("4x upscaler is not configured")
        side = int(_settings(svc)["upscaler"].get("max_output_side", 3072))
        if width * 4 > side or height * 4 > side:
            raise ValueError("4x output would exceed the configured maximum side")
    return profile


def _control(method, payload=None):
    key = os.environ.get("MIKUCHIN_UPSTREAM_API_KEY", "")
    port_text = os.environ.get("MIKUCHIN_NATIVE_OFFICIAL_PORT", "")
    if len(key) < 12 or not port_text.isdecimal():
        raise LocalImageError("local GPU operation requires a managed native supervisor")
    port = int(port_text)
    if not 1024 <= port <= 65535 or port == 15239:
        raise LocalImageError("invalid private official engine port")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=240)
    try:
        conn.request("POST", method, body=json.dumps(payload or {}).encode("utf-8"),
                     headers={"Authorization": "Bearer " + key,
                              "Content-Type": "application/json"})
        response = conn.getresponse()
        status = response.status
        raw = response.read(32768)
        if status != 200:
            raise LocalImageError("private engine refused GPU handoff: HTTP " + str(status))
        return json.loads(raw) if raw else {}
    except (OSError, http.client.HTTPException) as exc:
        raise LocalImageError("private engine unavailable for GPU handoff") from exc
    finally:
        conn.close()


def _save_handoff_slot(data_root):
    """Best-effort save of the *active* official engine slot.

    This is NOT a per-conversation snapshot: PolyStrata exposes only slot 0.
    The image GPU lock excludes concurrent Gateway inference while this is
    captured and restored. Conversation history remains authoritative, so a
    failed restore is recovered on the next request by normal prefill.
    """
    root = Path(data_root) / "kv-handoffs"
    # Without an explicitly enabled --slot-save-path, do not call a 501 API
    # or generate partial session files in an unexpected directory.
    if not root.is_dir() or root.is_symlink():
        return None
    name = "handoff-" + secrets.token_hex(16) + ".bin"
    file = root / name
    try:
        result = _control("/slots/0?action=save", {"filename": name})
        if not file.is_file() or file.is_symlink() or not file.stat().st_size:
            raise LocalImageError("official slot save produced no snapshot")
        if not int(result.get("n_saved", 0)):
            file.unlink(missing_ok=True)
            return None
        return name
    except (LocalImageError, OSError, ValueError) as exc:
        file.unlink(missing_ok=True)
        LOG.warning("Active-slot save unavailable; next chat will prefill (%s)", type(exc).__name__)
        return None


@contextlib.contextmanager
def gpu_handoff(svc, *, on_status=None):
    # Leave the official engine stopped until all GPU work has finished.
    # If the worker dies, OS byte-range lock is released automatically.
    root = Path(svc.root).parent
    with gpu_turn(root, exclusive=True, timeout=300):
        publish_state(root, "unloading")
        if on_status:
            on_status("Waiting for official model unload")
        snapshot = _save_handoff_slot(root)
        try:
            _control("/v1/unload?wait=180")
            yield
        finally:
            publish_state(root, "restoring")
            if on_status:
                on_status("Restoring official text model")
            try:
                _control("/v1/load")
                if snapshot:
                    if on_status:
                        on_status("Restoring active KV snapshot")
                    try:
                        _control("/slots/0?action=restore", {"filename": snapshot})
                    except (LocalImageError, ValueError, OSError) as exc:
                        # An engine restart or full-context prefill must not
                        # turn a successfully generated image into a retry.
                        LOG.warning("KV slot restore unavailable; next chat will prefill (%s)",
                                    type(exc).__name__)
            except LocalImageError:
                # Image files are already generated. Reload may be retried on
                # the next inference; do not turn a completed image into retry.
                LOG.exception("Official model reload failed after GPU job")
            finally:
                if snapshot:
                    (root / "kv-handoffs" / snapshot).unlink(missing_ok=True)
                publish_state(root, "idle")


def _image_png(raw):
    with Image.open(io.BytesIO(raw)) as im:
        if im.width * im.height > 20_000_000:
            raise LocalImageError("image exceeds supported pixel count")
        output = io.BytesIO()
        im.convert("RGB").save(output, format="PNG")
        return output.getvalue()


def _run(cmd, *, work, env=None, timeout=1200):
    log = Path(work) / "worker-process.log"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with log.open("wb") as output:
        process = subprocess.Popen(cmd, cwd=str(work), env=env,
                                   stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=flags)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait(timeout=15)
            raise LocalImageError("local image subprocess exceeded timeout") from exc
    if process.returncode:
        raise LocalImageError("local image subprocess failed with exit code " + str(process.returncode))


def _environment(profile):
    env = dict(os.environ)
    dirs = profile.get("lib_dirs", [])
    if isinstance(dirs, list):
        valid = [str(p) for p in dirs if isinstance(p, str) and Path(p).is_dir()]
        if valid:
            env["PATH"] = os.pathsep.join(valid + [env.get("PATH", "")])
    return env


def generate(svc, req, *, on_status=None, diagnostic_id=None):
    profile = validate(svc, req)
    w, h = map(int, req["size"].split("x"))
    ref = req.get("strata_reference_images", [])
    prompt = req.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt:
        raise LocalImageError("invalid prompt for local image generation")
    steps = int(req.get("steps") or 8)
    seed = req.get("seed")
    if seed is None:
        seed = random.SystemRandom().randrange(0, 2**31)
    with tempfile.TemporaryDirectory(prefix="mikuchin-qwen-") as temp:
        work = Path(temp)
        # sd-cli's -o uses printf-style batch numbering, including n=1.
        out = work / "generated_0.png"
        cmd = [profile["exe"], "--diffusion-model", profile["diffusion_model"],
               "--vae", profile["vae"], "--llm", profile["llm"]]
        if profile.get("llm_vision"):
            cmd += ["--llm_vision", profile["llm_vision"]]
        if ref:
            if len(ref) != 1 or not profile.get("llm_vision"):
                raise LocalImageError("reference image is unsupported by this local model")
            prefix, encoded = ref[0].split(",", 1)
            if not prefix.startswith("data:image/"):
                raise LocalImageError("invalid local reference image")
            source = work / "reference.png"
            source.write_bytes(_image_png(base64.b64decode(encoded, validate=True)))
            cmd += ["--ref-image", str(source)]
        lora_id = req.get("strata_lora_id", "none")
        if lora_id not in (None, "", "none"):
            entry = next(p for p in _settings(svc)["loras"] if p["id"] == lora_id)
            lora = Path(entry["path"])
            prompt += f" <lora:{lora.stem}:1>"
            cmd += ["--lora-model-dir", str(lora.parent), "--lora-apply-mode", "at_runtime"]
        cmd += ["-p", prompt, "--steps", str(steps), "--cfg-scale", "1.0",
                "--sampling-method", "euler", "-W", str(w), "-H", str(h),
                "-s", str(seed), "-o", str(work / "generated_%d.png")]
        if steps == 8:
            cmd += ["--sigmas", TURBO_SIGMAS]
        cmd += [str(a) for a in profile.get("args", [])]
        timeout = max(60, min(int(profile.get("timeout_seconds", 1200)), 3600))
        t0 = time.monotonic()
        postprocess = {}
        with gpu_handoff(svc, on_status=on_status):
            publish_state(Path(svc.root).parent, "generating")
            if on_status:
                on_status("Local Qwen-Image inference")
            _run(cmd, work=work, env=_environment(profile), timeout=timeout)
            if not out.is_file():
                raise LocalImageError("local Qwen-Image did not produce a PNG")
            image = _image_png(out.read_bytes())
            with Image.open(io.BytesIO(image)) as im:
                if im.size != (w, h):
                    raise LocalImageError("local image dimensions do not match request")
            dest = Path(svc.root) / "generated-images"
            dest.mkdir(parents=True, exist_ok=True)
            name = secrets.token_hex(16) + ".png"
            (dest / name).write_bytes(image)
            # One and only one GPU exclusive lease spans generation AND 4x.
            # Store the original before attempting enhancement: even if
            # Real-ESRGAN fails, never mislabel generated content as failed.
            try:
                if should_upscale(svc, req):
                    publish_state(Path(svc.root).parent, "upscaling")
                    started = time.monotonic()
                    postprocess["upscaled_png"] = _upscale_inside_gpu(svc, image, on_status=on_status)
                    postprocess["upscale_seconds"] = round(time.monotonic() - started, 2)
            except Exception as exc:
                postprocess["upscale_warning"] = type(exc).__name__
        return {"model": profile.get("model", profile["id"]), "size": req["size"],
                "strata": {"image_file": name, "seconds": round(time.monotonic()-t0, 2)},
                **postprocess}


def should_upscale(svc, req):
    mode = req.get("strata_upscale", "off")
    if mode not in ("off", "auto", "4x", None):
        raise ValueError("invalid 4x option")
    if mode in ("off", None) or not upscaler_ready(svc):
        return False
    w, h = map(int, req["size"].split("x"))
    max_side = int(_settings(svc)["upscaler"].get("max_output_side", 3072))
    if max(w, h) * 4 > max_side:
        return False
    if mode == "4x":
        return True
    prompt = req.get("prompt") or ""
    return bool(AUTO_ANIME.search(prompt) and not NOT_ANIME.search(prompt))


def _upscale_inside_gpu(svc, raw, *, on_status=None):
    """Called only with the worker's exclusive GPU handoff already held."""
    if not upscaler_ready(svc):
        raise LocalImageError("Real-ESRGAN 4x model is not configured")
    cfg = _settings(svc)["upscaler"]
    model = cfg.get("model", "realesrgan-x4plus-anime")
    image = _image_png(raw)
    with Image.open(io.BytesIO(image)) as im:
        width, height = im.size
    max_side = int(cfg.get("max_output_side", 3072))
    if max(width, height) * 4 > max_side:
        raise LocalImageError("upscaled dimensions exceed configured maximum")
    with tempfile.TemporaryDirectory(prefix="mikuchin-4x-") as temp:
        work = Path(temp)
        source, output = work / "original.png", work / "upscaled.png"
        source.write_bytes(image)
        cmd = [cfg["exe"], "-i", str(source), "-o", str(output),
               "-n", model, "-s", "4", "-m", str(cfg["model_dir"]),
               "-t", str(int(cfg.get("tile", 128))), "-g", str(int(cfg.get("gpu", 0))),
               "-j", "1:2:2", "-f", "png"]
        if on_status:
            on_status("Real-ESRGAN 4x upscale")
        _run(cmd, work=work, timeout=max(30, min(int(cfg.get("timeout_seconds", 180)), 1200)))
        if not output.is_file():
            raise LocalImageError("Real-ESRGAN produced no image")
        result = _image_png(output.read_bytes())
        with Image.open(io.BytesIO(result)) as im:
            if im.size != (width * 4, height * 4):
                raise LocalImageError("Real-ESRGAN produced incorrect dimensions")
        return result


def upscale(svc, raw, *, on_status=None):
    """Public/upstream-API 4x entrypoint; takes its own exclusive GPU turn."""
    with gpu_handoff(svc, on_status=on_status):
        publish_state(Path(svc.root).parent, "upscaling")
        return _upscale_inside_gpu(svc, raw, on_status=on_status)
