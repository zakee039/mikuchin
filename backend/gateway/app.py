"""Mikuchin-owned Gateway for an UNMODIFIED official PolyStrata HTTP server.

Inference streams through the official HTTP API; new chat, character, lore and
workflow state remains private to Mikuchin. Image tool and visible-answer-budget
semantics are refused until they have faithful adapters.

The Gateway transport and CRUD use the Python stdlib; optional character image
uploads use Pillow in the isolated official Python environment.
"""
from __future__ import annotations

import argparse
import contextlib
import hmac
import http.client
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

try:
    from .conversations import ConversationStore, MissingConversation, valid_id
    from .characters import CharacterStore, card_from_tavern
    from .workflows import WorkflowRuntime
    from .lore import search_sources
    from .image_jobs import ImageJobStore
    from . import image_providers
    from . import gallery
    from . import local_images
    from .gpu_gate import gpu_turn, GPUUnavailable, read_state
except ImportError:  # unittest discover -s backend/gateway imports app as a top-level module
    from conversations import ConversationStore, MissingConversation, valid_id
    from characters import CharacterStore, card_from_tavern
    from workflows import WorkflowRuntime
    from lore import search_sources
    from image_jobs import ImageJobStore
    import image_providers
    import gallery
    import local_images
    from gpu_gate import gpu_turn, GPUUnavailable, read_state

LOG = logging.getLogger("mikuchin.gateway")
MAX_BODY_BYTES = 8 * 1024 * 1024
INFERENCE_POSTS = frozenset((
    "/v1/chat/completions", "/v1/messages", "/v1/responses",
    "/v1/images/generations",
))
INFERENCE_GETS = frozenset(("/v1/models", "/models", "/api/models", "/metrics"))
UNPORTED_FIELDS = frozenset((
    "strata_image_tool", "answer_budget_tokens",
))
IMAGE_PATH = re.compile(r"^/v1/images/files/[a-f0-9]{32}\.png$")
SESSIONS = "/v1/strata/sessions"
SAMPLING_DEFAULT = "/v1/strata/sampling-default"
CHARACTERS = "/v1/strata/characters"
REFERENCE = CHARACTERS + "/reference/"
IMAGE_JOBS = "/v1/mikuchin/image-jobs"
IMAGE_SERVICES = "/v1/mikuchin/image-api-services"
IMAGE_MODELS = "/v1/mikuchin/image-models"
IMAGE_REFERENCE = "/v1/mikuchin/image-job-reference/"
GALLERY = "/v1/mikuchin/gallery"
GALLERY_THUMB = GALLERY + "/thumb/"
GALLERY_ITEM = GALLERY + "/item"
WEB_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "web"
STATIC_FILE = re.compile(r"^/web/([a-z][a-z0-9_-]{0,80}\.(?:js|css|svg))$")
STATIC_MIME = {"js":"text/javascript; charset=utf-8", "css":"text/css; charset=utf-8",
               "svg":"image/svg+xml", "html":"text/html; charset=utf-8"}


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, *, api_key: str, upstream_key: str,
                 upstream_host: str, upstream_port: int, allowed_origins=(),
                 conversations: ConversationStore | None = None,
                 characters: CharacterStore | None = None,
                 image_jobs: ImageJobStore | None = None):
        if not api_key or not upstream_key:
            raise ValueError("Both gateway and upstream API keys are required")
        if upstream_host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("The upstream service must be bound to loopback")
        if not 1 <= upstream_port <= 65535:
            raise ValueError("Invalid upstream port")
        self.api_key = api_key
        self.upstream_key = upstream_key
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.allowed_origins = frozenset(allowed_origins)
        self.conversations = conversations
        self.characters = characters
        self.image_jobs = image_jobs
        super().__init__(address, GatewayHandler)


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer
    protocol_version = "HTTP/1.1"
    server_version = "MikuchinGateway/0.1"

    def log_message(self, fmt, *args):
        # Never log raw request lines: /?q=... can contain chat content, and
        # per-session paths contain private conversation IDs. No headers,
        # query values, prompts, image data or Authorization enter this log.
        path = urlsplit(self.path).path
        if path.startswith(SESSIONS + "/"):
            path = SESSIONS + "/{id}"
        elif path.startswith(REFERENCE):
            path = REFERENCE + "{id}"
        elif path.startswith(IMAGE_REFERENCE):
            path = IMAGE_REFERENCE + "{id}"
        elif path.startswith(GALLERY_THUMB):
            path = GALLERY_THUMB + "{id}"
        elif path.startswith("/v1/images/files/"):
            path = "/v1/images/files/{image}"
        if len(path) > 100:
            path = "{other}"
        status = str(args[1]) if len(args) >= 2 else "unknown"
        LOG.info("client=%s method=%s path=%s status=%s",
                 self.client_address[0], self.command, path, status)

    def _json(self, status: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin and origin in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _error(self, status: int, message: str, code="gateway_error"):
        self.close_connection = True
        self._json(status, {"error": {"message": message, "type": code}})

    def _authorized(self):
        value = self.headers.get("Authorization", "")
        candidate = value[7:] if value.startswith("Bearer ") else ""
        if not candidate or not hmac.compare_digest(candidate, self.server.api_key):
            self._error(401, "Missing or invalid gateway API key", "unauthorized")
            return False
        origin = self.headers.get("Origin", "")
        if origin:
            # Requests from the gateway's own origin are normal; other origins
            # must be explicitly enabled (no wildcard CORS access).
            same_origin = (urlsplit(origin).netloc.lower() ==
                           self.headers.get("Host", "").lower())
            if not same_origin and origin not in self.server.allowed_origins:
                self._error(403, "Cross-origin request not permitted", "forbidden")
                return False
        return True

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        requested = self.headers.get("Access-Control-Request-Method", "")
        if origin in self.server.allowed_origins and requested in ("GET", "POST"):
            self.send_response(204)
            self._send_cors_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._error(403, "Cross-origin requests are disabled by default", "forbidden")

    def do_GET(self):
        # Public browser shell; all APIs, generated images and session data
        # remain behind the existing Bearer/Origin gate below.
        static_path = urlsplit(self.path).path
        if static_path in ("/", "/index.html", "/monitor.html") or STATIC_FILE.fullmatch(static_path):
            self._serve_static(static_path)
            return
        if not self._authorized():
            return
        if not self.path.startswith("/") or self.path.startswith("//"):
            self._error(400, "Invalid request target")
            return
        path = urlsplit(self.path).path
        if path in (GALLERY,GALLERY_ITEM) or path.startswith(GALLERY_THUMB):
            self._handle_gallery_get(path)
            return
        if path in (IMAGE_JOBS,IMAGE_SERVICES,IMAGE_MODELS) or path.startswith(IMAGE_REFERENCE):
            self._handle_image_get(path)
            return
        if path == CHARACTERS or path.startswith(REFERENCE):
            self._handle_character_get(path)
            return
        if path == SESSIONS or path.startswith(SESSIONS + "/") or path == SAMPLING_DEFAULT:
            self._handle_private("GET", path)
            return
        if path == "/health":
            upstream_health = {}
            try:
                conn = http.client.HTTPConnection(self.server.upstream_host,
                                                  self.server.upstream_port, timeout=2)
                try:
                    conn.request("GET", "/health", headers={
                        "Authorization": "Bearer " + self.server.upstream_key})
                    response = conn.getresponse()
                    reachable = response.status == 200
                    body = response.read(32768)
                    if reachable:
                        upstream_health = json.loads(body)
                finally:
                    conn.close()
            except (OSError, TimeoutError, http.client.HTTPException, ValueError):
                reachable = False
            image_catalog = ((image_providers.catalog(self.server.image_jobs) +
                              local_images.catalog(self.server.image_jobs)[0])
                             if self.server.image_jobs is not None else [])
            self._json(200 if reachable else 503, {
                "status": "ok" if reachable else "degraded",
                "component": "mikuchin-gateway", "official_polystrata_reachable": reachable,
                "model": str(upstream_health.get("model") or "official-polystrata")[:180],
                "max_context": upstream_health.get("max_context") or 0,
                "images": bool(upstream_health.get("images")),
                "image_generation": any(x.get("available") for x in image_catalog),
                "image_worker_ready": bool(self.server.image_jobs and
                                           self.server.image_jobs.worker_healthy()),
                "native_gpu": (read_state(self.server.image_jobs.root.parent)
                               if self.server.image_jobs else {"busy": False, "phase": "idle"}),
                "native_image_jobs": (self.server.image_jobs.activity()
                                      if self.server.image_jobs else {"running": 0, "drafts": 0, "phase": ""}),
                "native_upscaler_ready": bool(self.server.image_jobs and
                                              local_images.upscaler_ready(self.server.image_jobs)),
            })
            return
        if path not in INFERENCE_GETS and not IMAGE_PATH.fullmatch(path):
            self._error(404, "Endpoint is not yet available on the native gateway", "not_found")
            return
        if IMAGE_PATH.fullmatch(path) and self.server.image_jobs:
            ident=path[len("/v1/images/files/"):-4]
            try:
                file=gallery._file(self.server.image_jobs,ident)
                if file.is_file():
                    gallery.detail(self.server.image_jobs,ident)  # indexed, not arbitrary local file
                    self._binary("image/png",file.read_bytes())
                    return
            except (gallery.GalleryError,ValueError,OSError):
                pass
        self._proxy("GET")

    def _serve_static(self, path):
        if path in ("/", "/index.html"):
            name = "index.html"
        elif path == "/monitor.html":
            name = "monitor.html"
        else:
            match = STATIC_FILE.fullmatch(path)
            if match is None:
                self._error(404, "Unknown static asset", "not_found")
                return
            name = match.group(1)
        file = WEB_ROOT / name
        if not file.is_file() or file.is_symlink():
            self._error(404, "Static asset not found", "not_found")
            return
        try:
            if file.stat().st_size > 2 * 1024 * 1024:
                self._error(413, "Static asset too large", "invalid_asset")
                return
            data = file.read_bytes()
        except OSError:
            self._error(503, "Static asset unavailable", "unavailable")
            return
        content_type = STATIC_MIME[file.suffix.lstrip(".")]
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._authorized():
            return
        if not self.path.startswith("/") or self.path.startswith("//"):
            self._error(400, "Invalid request target")
            return
        path = urlsplit(self.path).path
        private = (path == SESSIONS or path.startswith(SESSIONS + "/")
                   or path == SAMPLING_DEFAULT or path == CHARACTERS
                   or path in (IMAGE_JOBS,IMAGE_SERVICES,GALLERY))
        if path not in INFERENCE_POSTS and not private:
            self._error(404, "Endpoint is not yet available on the native gateway", "not_found")
            return
        if self.headers.get("Transfer-Encoding"):
            self._error(411, "Chunked request bodies are not supported yet")
            return
        raw_length = self.headers.get("Content-Length", "")
        try:
            size = int(raw_length)
        except ValueError:
            self._error(411, "Content-Length is required")
            return
        if size < 0 or size > MAX_BODY_BYTES:
            self._error(413, "Request body exceeds gateway limit")
            return
        body = self.rfile.read(size)
        if len(body) != size:
            self._error(400, "Incomplete request body")
            return
        try:
            request = json.loads(body, parse_constant=lambda x: (_ for _ in ()).throw(
                ValueError("Non-finite JSON numbers are not permitted")))
        except (ValueError, UnicodeDecodeError):
            self._error(400, "Expected a JSON request body")
            return
        if not isinstance(request, dict):
            self._error(400, "Expected a JSON object")
            return
        if private:
            if path == GALLERY:
                self._handle_gallery_post(request)
            elif path in (IMAGE_JOBS,IMAGE_SERVICES):
                self._handle_image_post(path,request)
            elif path == CHARACTERS:
                self._handle_character_post(request)
            else:
                self._handle_private("POST", path, request)
            return
        unsupported = sorted(UNPORTED_FIELDS.intersection(request))
        if unsupported:
            self._error(501,
                        "Mikuchin semantics not yet ported: " + ", ".join(unsupported),
                        "feature_not_ported")
            return
        # The UI transmits the entire context each turn. These two fields are
        # application metadata, not a native KV snapshot or hidden engine state.
        if "strata_session_id" in request:
            try:
                valid_id(request.pop("strata_session_id"))
            except ValueError as exc:
                self._error(400, str(exc), "invalid_session")
                return
        if "mikuchin_stateless" in request:
            if request.pop("mikuchin_stateless") is not True:
                self._error(400, "mikuchin_stateless must be true", "invalid_request")
                return
        body = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._proxy("POST", body)

    def do_DELETE(self):
        if not self._authorized():
            return
        if not self.path.startswith("/") or self.path.startswith("//"):
            self._error(400, "Invalid request target")
            return
        path = urlsplit(self.path).path
        if path.startswith(SESSIONS + "/"):
            self._handle_private("DELETE", path)
        else:
            self._error(404, "Endpoint not found", "not_found")

    def _handle_private(self, method, path, request=None):
        store = self.server.conversations
        if store is None:
            self._error(503, "Native conversation store is not configured", "unavailable")
            return
        try:
            if path == SAMPLING_DEFAULT:
                if method == "GET":
                    result = {"sampling": store.default_sampling()}
                elif method == "POST":
                    result = store.save_default_sampling(request.get("sampling"))
                else:
                    self._error(405, "Method not allowed")
                    return
            elif path == SESSIONS:
                if method == "GET":
                    result = {"sessions": store.listing()}
                elif method == "POST":
                    result = store.save_messages(request.get("id"), request.get("web_messages"))
                else:
                    self._error(405, "Method not allowed")
                    return
            elif path.startswith(SESSIONS + "/"):
                ident = path[len(SESSIONS) + 1:]
                if method == "GET":
                    result = store.get(ident)
                elif method == "POST":
                    if request.get("action") == "lock_kv":
                        self._error(410, "Manual KV locking has been retired", "feature_retired")
                        return
                    result = store.change(ident, request.get("action"), request)
                elif method == "DELETE":
                    result = store.delete(ident)
                    if self.server.characters:
                        self.server.characters.forget_session(ident)
                else:
                    self._error(405, "Method not allowed")
                    return
            else:
                self._error(404, "Endpoint not found", "not_found")
                return
            self._json(200, result)
        except MissingConversation:
            self._error(404, "Conversation not found", "not_found")
        except (ValueError, TypeError, OverflowError) as exc:
            self._error(400, str(exc), "invalid_request")
        except (sqlite3.Error, OSError):
            LOG.exception("native conversation store failed")
            self._error(503, "Native conversation store is unavailable", "unavailable")

    def _handle_character_get(self, path):
        cards = self.server.characters
        if cards is None:
            self._error(503, "Native character store is not configured", "unavailable")
            return
        try:
            if path == CHARACTERS:
                self._json(200, cards.snapshot())
                return
            if not path.startswith(REFERENCE):
                self._error(404, "Character resource not found", "not_found")
                return
            reference = cards.image_file(path[len(REFERENCE):])
            if reference is None:
                self._error(404, "Character reference image not found", "not_found")
                return
            payload = reference.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError, TypeError) as exc:
            self._error(400, str(exc), "invalid_request")
        except (sqlite3.Error, OSError):
            LOG.exception("native character read failed")
            self._error(503, "Native character store is unavailable", "unavailable")

    def _handle_character_post(self, req):
        cards = self.server.characters
        sessions = self.server.conversations
        if cards is None or sessions is None:
            self._error(503, "Native character/session store is not configured", "unavailable")
            return
        try:
            action = req.get("action")
            if action == "save":
                result = {"card": cards.save(req.get("card"))}
            elif action == "import":
                result = {"card": cards.save(card_from_tavern(req.get("card")))}
            elif action == "delete":
                cards.remove(req.get("id"))
                result = {"deleted": True}
            elif action == "assign":
                ident = valid_id(req.get("session_id"))
                if sessions.has_messages(ident):
                    raise ValueError("角色只能在空白新会话中选择")
                cards.assign(ident, req.get("card_id"))
                result = {"saved": True}
            elif action == "reference_upload":
                result = {"card": cards.upload_reference(req.get("id"), req.get("data"))}
            elif action == "reference_remove":
                result = {"card": cards.remove_reference(req.get("id"))}
            elif action == "global":
                api = image_providers.catalog(self.server.image_jobs)
                models, loras = local_images.catalog(self.server.image_jobs)
                choices = {item["id"]: item for item in (api + models) if item["available"]}
                # Character/persona settings remain editable even when no
                # image provider has been configured on this fresh device.
                if not choices:
                    choices["default"] = {"family":"qwen_turbo","max_side":1024,
                                          "upscale_available":False,"available":True}
                result = {"global": cards.set_global(req.get("global"),
                    allowed_image_profiles=set(choices),
                    image_profile_configs={item_id: {
                        "family": item["family"], "max_side": item["max_side"],
                        "sizes": item.get("sizes","all"),
                        "available_loras": {l["id"] for l in loras if l["available"]},
                        "upscale_available": item.get("upscale_available",False)}
                        for item_id,item in choices.items()})}
            elif action in ("inspect_workflow", "prepare_workflow", "commit_workflow"):
                workflow = WorkflowRuntime(cards)
                if action == "inspect_workflow":
                    result = workflow.inspect(req.get("card_id"))
                elif action == "prepare_workflow":
                    ident = valid_id(req.get("session_id"))
                    result = workflow.prepare(ident, req.get("first_user_turn"))
                else:
                    ident = valid_id(req.get("session_id"))
                    result = workflow.commit(ident)
            elif action in ("retrieve", "test_retrieve"):
                query = req.get("query", "")
                if not isinstance(query, str) or len(query) > 4000:
                    raise ValueError("query must be text up to 4000 characters")
                card = cards.get(req.get("card_id")) if action == "test_retrieve" else (
                    cards.assigned_card(valid_id(req.get("session_id"))))
                result = search_sources(card.get("sources", []), query) if card else {
                    "snippets": [], "scanned_files": 0, "errors": [], "elapsed_ms": 0}
            else:
                raise ValueError("unknown character action")
            self._json(200, result)
        except (ValueError, TypeError, OverflowError) as exc:
            self._error(400, str(exc), "invalid_request")
        except (sqlite3.Error, OSError):
            LOG.exception("native character operation failed")
            self._error(503, "Native character store is unavailable", "unavailable")

    def _binary(self, mime, raw):
        self.send_response(200)
        self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(raw)))
        self.send_header("Cache-Control","private, no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _handle_image_get(self,path):
        jobs=self.server.image_jobs
        if jobs is None:
            self._error(503,"Native image task worker is not configured","unavailable")
            return
        try:
            if path == IMAGE_SERVICES:
                self._json(200,{"services":image_providers.list_services(jobs)})
            elif path == IMAGE_MODELS:
                models, loras = local_images.catalog(jobs)
                api = image_providers.catalog(jobs)
                for item in api:
                    item["upscale_available"] = local_images.upscaler_ready(jobs)
                self._json(200,{"models":models + api,"loras":loras})
            elif path == IMAGE_JOBS:
                from urllib.parse import parse_qs
                query=parse_qs(urlsplit(self.path).query)
                ident=query.get("id",[None])[0]
                kind=query.get("kind",[None])[0]
                self._json(200,jobs.listing(ident,kind=kind))
            elif path.startswith(IMAGE_REFERENCE):
                data,mime=jobs.reference_bytes(path[len(IMAGE_REFERENCE):])
                self._binary(mime,data)
            else:
                self._error(404,"Native image resource not found","not_found")
        except (ValueError,TypeError,OverflowError) as exc:
            self._error(400,str(exc),"invalid_request")
        except (sqlite3.Error,OSError):
            LOG.exception("native image read failed")
            self._error(503,"Native image storage unavailable","unavailable")

    def _handle_image_post(self,path,req):
        jobs=self.server.image_jobs
        if jobs is None:
            self._error(503,"Native image task worker is not configured","unavailable")
            return
        try:
            action=req.get("action")
            if path == IMAGE_SERVICES:
                if action == "save":
                    result={"service":image_providers.save_service(jobs,req.get("service"))}
                elif action == "delete":
                    image_providers.delete_service(jobs,req.get("id"))
                    result={"deleted":True}
                elif action == "discover":
                    result=image_providers.discover_models(jobs,req.get("connection"))
                else:
                    raise ValueError("unknown image API service action")
            elif path == IMAGE_JOBS:
                if action in ("delete","clear_completed"):
                    result=jobs.delete(req.get("id"),clear=action=="clear_completed")
                else:
                    result=jobs.submit(req)
            else:
                raise ValueError("unknown image action")
            self._json(200,result)
        except image_providers.ImageProviderError as exc:
            self._error(502,str(exc),"image_provider_error")
        except (ValueError,TypeError,OverflowError) as exc:
            self._error(400,str(exc),"invalid_request")
        except (sqlite3.Error,OSError):
            LOG.exception("native image operation failed")
            self._error(503,"Native image storage unavailable","unavailable")

    def _handle_gallery_get(self,path):
        jobs=self.server.image_jobs
        if jobs is None:
            self._error(503,"Native gallery is not configured","unavailable")
            return
        from urllib.parse import parse_qs
        params=parse_qs(urlsplit(self.path).query)
        try:
            if path == GALLERY:
                self._json(200,gallery.listing(jobs,
                    limit=int(params.get("limit",["60"])[0]),
                    offset=int(params.get("offset",["0"])[0]),
                    source=params.get("source",["all"])[0],
                    order=params.get("order",["newest"])[0]))
            elif path == GALLERY_ITEM:
                self._json(200,gallery.detail(jobs,params.get("id",[None])[0]))
            elif path.startswith(GALLERY_THUMB):
                data=gallery.thumbnail(jobs,path[len(GALLERY_THUMB):])
                if data is None:
                    self._error(404,"Gallery thumbnail not found","not_found")
                else:
                    self._binary("image/jpeg",data)
            else:
                self._error(404,"Gallery resource not found","not_found")
        except (gallery.GalleryError,ValueError,TypeError,OverflowError) as exc:
            self._error(400,str(exc),"invalid_request")
        except (OSError,sqlite3.Error):
            LOG.exception("native gallery read failed")
            self._error(503,"Native gallery storage unavailable","unavailable")

    def _handle_gallery_post(self,req):
        jobs=self.server.image_jobs
        if jobs is None:
            self._error(503,"Native gallery is not configured","unavailable")
            return
        try:
            action=req.get("action")
            if action == "nsfw":
                result=gallery.set_nsfw(jobs,req.get("id"),req.get("nsfw"))
            elif action == "nsfw_many":
                result=gallery.set_nsfw_many(jobs,req.get("ids"),req.get("nsfw"))
            elif action == "delete":
                result=gallery.delete_many(jobs,req.get("ids"))
            elif action == "delete_variant":
                result=gallery.delete_variant(jobs,req.get("id"),req.get("variant"))
            elif action == "repair":
                result=gallery.repair(jobs)
            else:
                raise ValueError("unknown gallery action")
            self._json(200,result)
        except (gallery.GalleryError,ValueError,TypeError) as exc:
            self._error(400,str(exc),"invalid_request")
        except (sqlite3.Error,OSError):
            LOG.exception("native gallery operation failed")
            self._error(503,"Native gallery storage unavailable","unavailable")

    def _proxy(self, method: str, body: bytes | None = None):
        root = self.server.image_jobs.root.parent if self.server.image_jobs else None
        try:
            with gpu_turn(root, timeout=1) if root else contextlib.nullcontext():
                self._proxy_unguarded(method, body)
        except GPUUnavailable:
            self._error(503, "Native GPU is reserved for an image task", "gpu_busy")

    def _proxy_unguarded(self, method: str, body: bytes | None = None):
        conn = http.client.HTTPConnection(self.server.upstream_host,
                                          self.server.upstream_port, timeout=1800)
        sent_headers = False
        headers = {
            "Authorization": "Bearer " + self.server.upstream_key,
            "Accept": self.headers.get("Accept", "application/json"),
            "Accept-Encoding": "identity",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, self.path, body=body, headers=headers)
            upstream = conn.getresponse()
            # Do not buffer SSE or tool-call events. Force close framing for
            # clients; upstream's chunking is decoded by HTTPResponse.read1().
            self.send_response(upstream.status)
            for name in ("Content-Type", "Retry-After"):
                value = upstream.getheader(name)
                if value is not None:
                    self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_cors_headers()
            self.end_headers()
            sent_headers = True
            self.close_connection = True
            while True:
                data = upstream.read1(65536)
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            # Never retry a POST automatically: upstream may have accepted it.
            LOG.warning("upstream failure class=%s method=%s", type(exc).__name__, method)
            if not sent_headers:
                self._error(502, "Official PolyStrata is unavailable", "bad_gateway")
            self.close_connection = True
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="Native PolyStrata Mikuchin development gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15249,
                        help="Isolated development port; production is planned for 15239")
    parser.add_argument("--upstream-port", type=int, default=15240)
    args = parser.parse_args()
    gateway_key = os.environ.get("MIKUCHIN_GATEWAY_API_KEY", "")
    upstream_key = os.environ.get("MIKUCHIN_UPSTREAM_API_KEY", "")
    if not gateway_key or not upstream_key:
        parser.error("Set MIKUCHIN_GATEWAY_API_KEY and MIKUCHIN_UPSTREAM_API_KEY")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    origins = tuple(x.strip() for x in os.environ.get("MIKUCHIN_ALLOWED_ORIGINS", "").split(",")
                    if x.strip())
    data_dir = os.environ.get("MIKUCHIN_NATIVE_DATA_DIR") or ConversationStore.default_root()
    conversations = ConversationStore(data_dir)
    characters = CharacterStore(os.path.join(data_dir, "character"))
    images = ImageJobStore(os.path.join(data_dir, "images"))
    with GatewayServer((args.host, args.port), api_key=gateway_key,
                       upstream_key=upstream_key, upstream_host="127.0.0.1",
                       upstream_port=args.upstream_port, allowed_origins=origins,
                       conversations=conversations, characters=characters,
                       image_jobs=images) as server:
        LOG.info("Gateway on %s:%d; official PolyStrata on 127.0.0.1:%d",
                 args.host, args.port, args.upstream_port)
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
