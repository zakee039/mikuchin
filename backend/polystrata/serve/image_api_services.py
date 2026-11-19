"""Mikuchin image-service registry and OpenAI Images compatible HTTP adapter.

This module does not import PolyStrata GPU code. API credentials live only in
the deployment's server-side config directory and are never returned by GET.
"""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

_LOCK = threading.RLock()
_IDENT = re.compile(r"^api-[a-z0-9-]{6,64}$")
_ALLOWED_PROXY = {"http", "https", "socks5", "socks5h"}
_MAX_IMAGE = 12 * 1024 * 1024
_MAX_OUTPUT = 20 * 1024 * 1024
_MAX_API_JSON = 40 * 1024 * 1024  # 20 MB image encoded as base64 plus JSON overhead
_MAX_REFERENCES = 8
_CONNECT_TIMEOUT = 15
LOCAL_SIZES = (384, 512, 768, 1024)
STANDARD_SIZES = (
    (1024, 1024), (1536, 1536), (2048, 2048), (1536, 1024), (1024, 1536),
    (1536, 864), (2560, 1440), (3840, 2160), (2160, 3840),
)


def allowed_image_size(mode: str, width: int, height: int) -> bool:
    """Width x height, never height x width. Providers may impose tighter limits."""
    if mode == "standard":
        return (width, height) in STANDARD_SIZES
    if mode == "all":  # Historic name; now the local-recommended preset pack.
        return width in LOCAL_SIZES and height in LOCAL_SIZES
    if mode == "square":  # Historic saved service: keep its existing capability.
        return (width, height) == (1024, 1024)
    if mode == "custom":
        return all(256 <= value <= 4096 and value % 16 == 0
                   for value in (width, height))
    return False


class ImageServiceError(ValueError):
    pass


class ImageProviderError(RuntimeError):
    pass


def _url(value, *, proxy=False):
    if not isinstance(value, str) or len(value) > 2048:
        raise ImageServiceError("invalid URL")
    val = value.strip().rstrip("/")
    parsed = urlsplit(val)
    if parsed.scheme not in (_ALLOWED_PROXY if proxy else {"http", "https"}):
        raise ImageServiceError("unsupported URL scheme")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ImageServiceError("URL needs a hostname, without user info, query or fragment")
    if not proxy and (parsed.path.endswith("/images/generations") or parsed.path.endswith("/images/edits")):
        raise ImageServiceError("Base URL must end before /images/generations or /images/edits")
    if proxy and parsed.path not in ("", "/"):
        raise ImageServiceError("proxy URL must not include a path")
    return val


def _config_dir(svc):
    override = os.environ.get("MIKUCHIN_IMAGE_SERVICES_FILE")
    if override:
        return Path(override)
    sessions = getattr(svc, "session_v1", None)
    if sessions:
        return sessions.root.parent / "config" / "image-api-services.json"
    return Path(getattr(svc, "config_path", "") or ".").resolve().parent / "image-api-services.json"


def _read(svc):
    p = _config_dir(svc)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("services"), list):
        raise ImageServiceError("invalid image API service registry")
    return data["services"]


def _write(svc, values):
    p = _config_dir(svc)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + "." + secrets.token_hex(4) + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as f:
            json.dump({"services": values}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def public(entry):
    return {k: entry[k] for k in (
        "id", "name", "base_url", "model", "proxy", "proxy_url",
        "reference_mode", "negative", "seed", "steps", "sizes", "concurrency",
        "timeout_seconds", "connect_timeout_seconds",
    ) if k in entry} | {"has_key": bool(entry.get("api_key")),
                       "concurrency": entry.get("concurrency", 1),
                       "timeout_seconds": entry.get("timeout_seconds", 240),
                       "connect_timeout_seconds": entry.get("connect_timeout_seconds", _CONNECT_TIMEOUT)}


def list_services(svc):
    with _LOCK:
        return [public(s) for s in _read(svc)]


def get(svc, ident):
    with _LOCK:
        return next((dict(s) for s in _read(svc) if s.get("id") == ident), None)


def save_service(svc, payload):
    if not isinstance(payload, dict):
        raise ImageServiceError("service must be an object")
    with _LOCK:
        entries = _read(svc)
        ident = payload.get("id") or "api-" + secrets.token_hex(8)
        if not isinstance(ident, str) or not _IDENT.fullmatch(ident):
            raise ImageServiceError("invalid image API service id")
        prev = next((s for s in entries if s.get("id") == ident), None)
        if prev is None and len(entries) >= 30:
            raise ImageServiceError("at most 30 image API services")
        name = payload.get("name")
        model = payload.get("model")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ImageServiceError("service name must be 1–80 characters")
        if not isinstance(model, str) or not 1 <= len(model.strip()) <= 120:
            raise ImageServiceError("model ID must be 1–120 characters")
        ref = payload.get("reference_mode", "none")
        if ref not in ("multi", "single", "none"):
            raise ImageServiceError("reference mode must be multi, single or none")
        sizes = payload.get("sizes", "standard")
        if sizes not in ("standard", "all", "square", "custom"):
            raise ImageServiceError("invalid size preset")
        concurrency = payload.get("concurrency", 1)
        if type(concurrency) is not int or not 1 <= concurrency <= 20:
            raise ImageServiceError("API concurrency must be between 1 and 20")
        timeout_seconds = payload.get("timeout_seconds", 240)
        if type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 1200:
            raise ImageServiceError("API timeout must be between 30 and 1200 seconds")
        connect_timeout = payload.get("connect_timeout_seconds", _CONNECT_TIMEOUT)
        if type(connect_timeout) is not int or not 5 <= connect_timeout <= 60:
            raise ImageServiceError("API connection timeout must be between 5 and 60 seconds")
        proxy = payload.get("proxy", False)
        if not isinstance(proxy, bool):
            raise ImageServiceError("proxy must be a boolean")
        proxy_url = _url(payload.get("proxy_url"), proxy=True) if proxy else ""
        key = payload.get("api_key", "")
        if key is None:
            key = ""
        if not isinstance(key, str) or len(key) > 1024 or "\r" in key or "\n" in key:
            raise ImageServiceError("invalid API key")
        # Never silently send the existing credential to a newly edited origin.
        if not key and prev:
            if _url(payload.get("base_url")) != prev.get("base_url"):
                raise ImageServiceError("Base URL changed; enter an API key for the new endpoint")
            key = prev.get("api_key", "")
        entry = {
            "id": ident, "name": name.strip(), "base_url": _url(payload.get("base_url")),
            "api_key": key, "model": model.strip(), "proxy": proxy,
            "proxy_url": proxy_url, "reference_mode": ref,
            "negative": payload.get("negative") is True,
            "seed": payload.get("seed") is True,
            "steps": payload.get("steps") is True, "sizes": sizes,
            "concurrency": concurrency,
            "timeout_seconds": timeout_seconds,
            "connect_timeout_seconds": connect_timeout,
        }
        entries = [s for s in entries if s.get("id") != ident]
        entries.append(entry)
        _write(svc, entries)
        return public(entry)


def delete_service(svc, ident):
    with _LOCK:
        entries = _read(svc)
        new = [s for s in entries if s.get("id") != ident]
        if len(new) == len(entries):
            raise ImageServiceError("image API service not found")
        _write(svc, new)


def catalog(svc):
    result = []
    for s in list_services(svc):
        result.append({
            "id": s["id"], "name": f'{s["name"]}-[{s["model"]}]', "family": "api",
            "type": "api", "available": bool(s["has_key"]),
            "steps": 8, "max_side": 4096 if s["sizes"] in ("standard", "custom") else 1024,
            "sizes": s["sizes"], "reference_mode": s["reference_mode"],
            "negative": s["negative"], "seed": s["seed"],
            "supports_steps": s["steps"], "model": s["model"],
            "upscale_available": bool(getattr(svc, "images", None) and
                                      svc.images.cfg.get("upscaler", {}).get("enabled")),
        })
    return result




# OpenAI-compatible providers may expose both chat and image models from
# GET /models. Metadata is advisory; no model is confirmed to generate images.
_IMAGE_NAMES = re.compile(
    r"(image|imagen|dall[-_ ]?e|gpt[-_ ]?image|flux|seedream|"
    r"ideogram|recraft|stable[-_ ]?diffusion|sdxl|qwen[-_ ]?image|"
    r"kolors|hunyuan[-_ ]?image|banana|z[-_ ]?image)", re.IGNORECASE
)


def discover_models(svc, payload):
    """Probe GET <Base URL>/models using unsaved form inputs.

    A saved service ID allows reusing its secret if the editing form leaves
    API Key blank. Results never contain credentials and are not persisted.
    """
    if not isinstance(payload, dict):
        raise ImageServiceError("model discovery expects a JSON object")
    ident = payload.get("id")
    existing = None
    if ident is not None:
        if not isinstance(ident, str) or not _IDENT.fullmatch(ident):
            raise ImageServiceError("invalid service ID")
        existing = get(svc, ident)
        if existing is None:
            raise ImageServiceError("saved service not found")
    base = _url(payload.get("base_url"))
    proxy = payload.get("proxy", False)
    if not isinstance(proxy, bool):
        raise ImageServiceError("proxy must be a boolean")
    proxy_url = _url(payload.get("proxy_url"), proxy=True) if proxy else ""
    key = payload.get("api_key", "")
    if not isinstance(key, str) or len(key) > 1024 or "\r" in key or "\n" in key:
        raise ImageServiceError("invalid API key")
    if not key and existing:
        if base != existing.get("base_url"):
            raise ImageServiceError("Base URL changed; enter an API key before discovering models")
        key = existing.get("api_key", "")
    service = {"proxy": proxy, "proxy_url": proxy_url}
    auth = {"Authorization": "Bearer " + key} if key else {}
    try:
        with _session(service) as session:
            with session.get(base + "/models", headers=auth, timeout=(8, 20),
                             allow_redirects=False, stream=True) as response:
                if not response.ok:
                    raise ImageProviderError(
                        f"model catalog HTTP {response.status_code}: {str(response.reason)[:80]}")
                # Bound memory for providers returning very large model lists.
                chunks, total = [], 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > 2 * 1024 * 1024:
                        raise ImageProviderError("model catalog exceeds 2 MB")
                    chunks.append(chunk)
                try:
                    raw = json.loads(b"".join(chunks))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise ImageProviderError("provider returned an invalid models JSON") from exc
    except requests.RequestException as exc:
        raise ImageProviderError("could not fetch model catalog: " + str(exc)[:240]) from exc

    # The OpenAI shape is {"data":[{"id":"..."}]}; some gateways
    # use {"models":[...]}, and some return model IDs as strings.
    items = raw.get("data", raw.get("models")) if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ImageProviderError("provider does not return an OpenAI-compatible model list")
    models, seen = [], set()
    for item in items:
        if isinstance(item, str):
            ident, label, metadata = item, item, ""
        elif isinstance(item, dict):
            ident = item.get("id") or item.get("model")
            label = item.get("name") or item.get("display_name") or ident
            metadata = " ".join(str(item.get(field) or "")[:160] for field in
                                ("type", "modality", "capabilities", "description"))
        else:
            continue
        if not isinstance(ident, str) or not 0 < len(ident) <= 120 or ident in seen:
            continue
        if not isinstance(label, str):
            label = ident
        seen.add(ident)
        models.append({"id": ident, "name": label[:160],
                       "image_likely": bool(_IMAGE_NAMES.search(ident + " " + label + " " + metadata))})
    models.sort(key=lambda item: (not item["image_likely"], item["id"].casefold()))
    return {"models": models[:500], "total": len(models),
            "truncated": len(models) > 500}

def _reference(data_url):
    if not isinstance(data_url, str) or len(data_url) > _MAX_IMAGE * 2:
        raise ImageServiceError("reference image is too large")
    m = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)", data_url)
    if not m:
        raise ImageServiceError("reference must be a base64 PNG/JPEG/WebP image")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
        if not 0 < len(raw) <= _MAX_IMAGE:
            raise ValueError("size")
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP") or im.width * im.height > 28_000_000:
                raise ValueError("format/dimensions")
            image = im.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
        if output.tell() > _MAX_IMAGE:
            raise ValueError("converted image too large")
        return output.getvalue()
    except (ValueError, OSError, base64.binascii.Error) as exc:
        raise ImageServiceError("invalid reference image") from exc


def select_references(req, mode):
    refs = req.get("strata_reference_images")
    if refs is None:
        refs = [req["strata_reference_image"]] if req.get("strata_reference_image") else []
    if not isinstance(refs, list) or len(refs) > _MAX_REFERENCES:
        raise ImageServiceError("reference image list must contain at most 8 images")
    if mode == "none":
        return []
    if mode == "single":
        refs = refs[:1]
    return [_reference(item) for item in refs]


def _is_public_address(url, through_proxy=False):
    """Image URLs returned by remote providers cannot become an internal-network SSRF proxy."""
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        return False
    if through_proxy:
        # SOCKS5H resolves remotely: never leak DNS by resolving here first.
        host = p.hostname.lower().rstrip(".")
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host and not host.endswith((".local", ".localhost", ".internal", ".home.arpa"))
    try:
        return all(ipaddress.ip_address(record[4][0]).is_global
                   for record in socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM))
    except (socket.gaierror, ValueError, OSError):
        return False


def _png(raw):
    if not raw or len(raw) > _MAX_OUTPUT:
        raise ImageProviderError("provider image response exceeds 20 MB")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > 35_000_000:
                raise ImageProviderError("provider image too large")
            out = io.BytesIO()
            im.convert("RGBA").save(out, format="PNG")
            return out.getvalue()
    except (OSError, ValueError) as exc:
        raise ImageProviderError("provider returned an invalid image") from exc


def _session(service):
    session = requests.Session()
    session.trust_env = False   # direct means truly direct, without OS HTTP_PROXY
    if service["proxy"]:
        url = service["proxy_url"]
        if urlsplit(url).scheme.startswith("socks"):
            try:
                import socks  # noqa: F401 (PySocks, installed with requirements)
            except ImportError as exc:
                raise ImageProviderError("SOCKS5 proxy requires PySocks (pip install PySocks)") from exc
        session.proxies = {"http": url, "https": url}
    return session


def _provider_error(response, payload=None):
    try:
        obj = payload if payload is not None else response.json()
        message = obj.get("error", {}).get("message") if isinstance(obj.get("error"), dict) else obj.get("message")
    except (ValueError, AttributeError):
        message = None
    return f"image API HTTP {response.status_code}: {str(message or response.reason)[:320]}"


def _read_json_response(response, *, on_bytes=None):
    """Read and bound a streamed API response; never silently accept partial JSON.

    A mock response without iter_content keeps compatibility with the existing
    in-memory API tests. Real requests always use stream=True and this path.
    """
    if not callable(getattr(response, "iter_content", None)):
        return response.json()
    chunks, total = [], 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if on_bytes is not None:
            on_bytes(total)
        if total > _MAX_API_JSON:
            raise ImageProviderError("image API JSON response exceeds 40 MB")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ImageProviderError(
            f"image API returned incomplete/invalid JSON ({total} bytes received)") from exc


def _network_trace(job_id, route, phase, elapsed, *, status=None, received=None, error=None):
    """Per-task metadata only: never log prompts, images, proxy URLs or tokens."""
    if not isinstance(job_id, str) or not re.fullmatch(r"img-[0-9a-f]{24}", job_id):
        return
    parts = [f"job={job_id}", f"route={route}", f"phase={phase}",
             f"elapsed={elapsed:.2f}s"]
    if status is not None:
        parts.append(f"http={status}")
    if received is not None:
        parts.append(f"received={received}")
    if error:
        parts.append(f"error={error}")
    print("[mikuchin:image-api] " + " ".join(parts), flush=True)


def generate(svc, req, *, ident=None, on_status=None, diagnostic_id=None):
    """Call standard /images/generations or /images/edits; return Mikuchin's PNG response shape."""
    ident = ident or req.get("strata_image_profile")
    service = get(svc, ident)
    if not service:
        raise ImageServiceError("image API service not found")
    if not service.get("api_key"):
        raise ImageServiceError("image API key not configured")
    timeout_seconds = service.get("timeout_seconds", 240)
    connect_timeout = service.get("connect_timeout_seconds", _CONNECT_TIMEOUT)
    prompt = req.get("prompt")
    if not isinstance(prompt, str) or not 0 < len(prompt.strip()) <= 16000:
        raise ImageServiceError("prompt must be 1–16000 characters")
    size = req.get("size") or "1024x1024"
    if not isinstance(size, str) or not re.fullmatch(r"\d{3,4}x\d{3,4}", size):
        raise ImageServiceError("invalid image size")
    w, h = map(int, size.split("x"))
    if not allowed_image_size(service["sizes"], w, h):
        raise ImageServiceError("size is not available for this API service")
    refs = select_references(req, service["reference_mode"])
    params = {"model": service["model"], "prompt": prompt, "size": size, "n": 1}
    if service["negative"] and req.get("negative_prompt"):
        params["negative_prompt"] = req["negative_prompt"]
    if service["seed"] and req.get("seed") not in ("", None):
        params["seed"] = int(req["seed"])
    if service["steps"] and req.get("steps") is not None:
        params["steps"] = int(req["steps"])
    auth = {"Authorization": "Bearer " + service["api_key"]}
    def stage(value):
        if on_status is not None:
            on_status(value)

    start = time.monotonic()
    route = "proxy" if service["proxy"] else "direct"
    phase, received, http_status = "request_headers", 0, None
    def trace(event, *, error=None):
        _network_trace(diagnostic_id, route, event, time.monotonic()-start,
                       status=http_status, received=received, error=error)

    stage("连接 API / 等待响应头")
    trace("request_start")
    url = service["base_url"] + ("/images/edits" if refs else "/images/generations")
    try:
        with _session(service) as session:
            if refs:
                files = [("image" if len(refs) == 1 else "image[]",
                          (f"ref-{i}.png", raw, "image/png")) for i, raw in enumerate(refs)]
                response = session.post(url, headers=auth, data=params, files=files,
                                        timeout=(connect_timeout, timeout_seconds), stream=True)
            else:
                response = session.post(url, headers={**auth, "Content-Type":"application/json"},
                                        json=params, timeout=(connect_timeout, timeout_seconds),
                                        stream=True)
            http_status = getattr(response, "status_code", None)
            trace("response_headers")
            phase = "response_body"
            stage("正在接收 API 响应体")
            try:
                def count_response_bytes(value):
                    nonlocal received
                    received = value
                obj = _read_json_response(response, on_bytes=count_response_bytes)
            except ImageProviderError as exc:
                if not response.ok:
                    raise ImageProviderError(
                        f"image API HTTP {response.status_code}: incomplete/invalid response body") from exc
                raise
            finally:
                if callable(getattr(response, "close", None)):
                    response.close()
            trace("response_body_complete")
            if not response.ok:
                raise ImageProviderError(_provider_error(response, obj))
            try:
                data = obj["data"]
                item = data[0]
                if not isinstance(item, dict):
                    raise TypeError()
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ImageProviderError("provider returned an invalid OpenAI Images response") from exc
            if item.get("b64_json"):
                try:
                    image = base64.b64decode(item["b64_json"], validate=True)
                except (ValueError, base64.binascii.Error) as exc:
                    raise ImageProviderError("invalid base64 image response") from exc
            elif item.get("url"):
                stage("正在下载生成图片")
                uri = item["url"]
                if not _is_public_address(uri, service["proxy"]):
                    raise ImageProviderError("provider returned an unsafe image URL; use base64 response")
                phase, received, http_status = "download_headers", 0, None
                trace("download_start")
                result = session.get(uri, timeout=(connect_timeout,timeout_seconds),
                                     allow_redirects=False, stream=True)
                http_status = getattr(result, "status_code", None)
                trace("download_headers")
                phase = "download_body"
                try:
                    if not result.ok or 300 <= result.status_code < 400:
                        raise ImageProviderError("could not download provider image")
                    chunks, total = [], 0
                    for chunk in result.iter_content(65536):
                        total += len(chunk)
                        received = total
                        if total > _MAX_OUTPUT:
                            raise ImageProviderError("provider image exceeds 20 MB")
                        chunks.append(chunk)
                    image = b"".join(chunks)
                finally:
                    result.close()
                trace("download_complete")
            else:
                raise ImageProviderError("provider returned no b64_json or image URL")
    except requests.ConnectTimeout as exc:
        trace("network_error", error="ConnectTimeout")
        raise ImageProviderError(
            f"API 连接建立超时：实际 {time.monotonic()-start:.1f}s，"
            f"连接上限 {connect_timeout}s，路线 {route}，阶段 {phase}。"
            "请求是否到达上游未知，请先核对用量再重试。") from exc
    except requests.ReadTimeout as exc:
        elapsed = time.monotonic() - start
        trace("network_error", error="ReadTimeout")
        if phase in ("request_headers", "download_headers"):
            detail = ("尚未收到响应头；可能在 DNS/TCP/TLS 或等待首次响应。"
                      "不能仅凭 requests.ReadTimeout 判定已等待完整的读取超时。")
        else:
            detail = f"响应体接收中断（已收到 {received} 字节）。"
        raise ImageProviderError(
            f"API 网络超时：实际 {elapsed:.1f}s，阶段 {phase}，路线 {route}；"
            f"连接上限 {connect_timeout}s，读取上限 {timeout_seconds}s。{detail}"
            "上游可能仍在处理，勿盲目重试。") from exc
    except requests.RequestException as exc:
        elapsed = time.monotonic() - start
        trace("network_error", error=type(exc).__name__)
        reason = str(exc)
        if "IncompleteRead" in reason or "Connection broken" in reason:
            explanation = "响应体不完整，连接被提前关闭"
        elif "write operation timed out" in reason.lower():
            explanation = "发送请求过程中发生写入超时"
        else:
            explanation = "网络连接异常"
        raise ImageProviderError(
            f"API {explanation}：实际 {elapsed:.1f}s，阶段 {phase}，路线 {route}，"
            f"已接收 {received} 字节；{type(exc).__name__}。"
            "请求是否在上游完成未知，请先核对用量。") from exc
    except ImageProviderError:
        trace("provider_error", error="ImageProviderError")
        raise
    stage("正在处理生成图片")
    png = _png(image)
    up = {"upscale_applied": False}
    original_png = None
    upscale_requested = req.get("strata_upscale") == "4x"
    if upscale_requested:
        stage("正在执行本地 4 倍超分")
        cfg = (getattr(getattr(svc, "images", None), "cfg", {}) or {}).get("upscaler") or {}
        if not cfg.get("enabled"):
            up["upscale_error"] = "本机未配置超分组件，已保留原图"
        else:
            try:
                from serve.upscale import _upscale_one, png_size
                original_w, original_h = png_size(png)
                if max(original_w, original_h) * 4 > 6144:
                    raise ValueError("超分后最长边不能超过 6144 像素")
                improved, seconds = _upscale_one(png, cfg)
                original_png = png
                png = improved
                up["upscale_applied"] = True
                up["upscale_seconds"] = seconds
                up["upscale_output_size"] = f"{original_w*4}x{original_h*4}"
            except Exception as exc:
                up["upscale_error"] = f"{type(exc).__name__}: {exc}"[:300]
                # Failure never discards a successfully generated original.
                png = original_png or png
                original_png = None
    stage("正在保存图片")
    original_name = None
    if getattr(svc, "session_v1", None):
        folder = svc.session_v1.root / "generated-images"
        folder.mkdir(parents=True, exist_ok=True)
        if original_png is not None:
            original_name = secrets.token_hex(16) + ".png"
            (folder / original_name).write_bytes(original_png)
        (folder / (name := secrets.token_hex(16) + ".png")).write_bytes(png)
    else:
        name = None
    if original_name:
        up["upscale_original_files"] = [original_name]
    if up["upscale_applied"]:
        size = up["upscale_output_size"]
    return {
        "created": int(time.time()), "model": service["model"], "size": size,
        "output_format": "png",
        "data": [{"b64_json": base64.b64encode(png).decode("ascii"),
                  "revised_prompt": item.get("revised_prompt") or prompt}],
        "strata": {"image_profile": service["id"], "provider": "api",
                   "reference_count": len(refs), "seconds": round(time.monotonic()-start,2),
                   "image_file": name, **up}
    }
