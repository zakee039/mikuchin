"""Mikuchin OpenAI-compatible image service regression checks (no network)."""
import base64
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "polystrata"))
from serve import image_api_services as api


def tiny_image():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 180, 100)).save(out, format="PNG")
    return out.getvalue()


def ref(data):
    return "data:image/png;base64," + base64.b64encode(data).decode()


class FakeResponse:
    ok = True
    status_code = 200
    def __init__(self, data):
        self.data = data
    def json(self):
        return {"data": [{"b64_json": base64.b64encode(self.data).decode()}]}


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.data)


class ImageApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"MIKUCHIN_IMAGE_SERVICES_FILE": str(root / "secrets.json")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.svc = SimpleNamespace(session_v1=SimpleNamespace(root=root / "chat"))
        self.base = {
            "name": "Example", "base_url": "https://images.example.test/v1",
            "model": "custom-model", "api_key": "test-api-key", "reference_mode": "multi",
            "proxy": False, "negative": False, "seed": False, "steps": False,
            "sizes": "standard",
        }

    def test_save_secrets_update_and_delete(self):
        result = api.save_service(self.svc, self.base)
        self.assertEqual(result["has_key"], True)
        self.assertNotIn("api_key", str(result))
        self.assertEqual(len(api.list_services(self.svc)), 1)
        updated = {**self.base, "id": result["id"], "name": "Updated", "api_key": "",
                   "proxy": True, "proxy_url": "socks5h://127.0.0.1:7897"}
        api.save_service(self.svc, updated)
        saved = api.get(self.svc, result["id"])
        self.assertEqual(saved["api_key"], "test-api-key")
        self.assertEqual(saved["proxy_url"], updated["proxy_url"])
        self.assertEqual(api.catalog(self.svc)[0]["reference_mode"], "multi")
        api.delete_service(self.svc, result["id"])
        self.assertEqual(api.list_services(self.svc), [])

    def test_reference_downgrade(self):
        urls = [ref(tiny_image())] * 3
        req = {"strata_reference_images": urls}
        self.assertEqual(len(api.select_references(req, "multi")), 3)
        self.assertEqual(len(api.select_references(req, "single")), 1)
        self.assertEqual(len(api.select_references(req, "none")), 0)
        with self.assertRaises(api.ImageServiceError):
            api.select_references({"strata_reference_images": ["file:///etc/passwd"]}, "multi")

    def test_image_generation_json_and_persistence(self):
        item = api.save_service(self.svc, self.base)
        sess = FakeSession(tiny_image())
        with patch.object(api, "_session", return_value=sess):
            result = api.generate(self.svc, {
                "strata_image_profile": item["id"], "prompt": "test",
                "size": "1024x1024",
            })
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["strata"]["reference_count"], 0)
        name = result["strata"]["image_file"]
        self.assertTrue((self.svc.session_v1.root / "generated-images" / name).is_file())
        self.assertTrue(sess.calls[0][0].endswith("/images/generations"))
        self.assertNotIn("api_key", str(result))

    def test_edits_fallback_to_first_image(self):
        service = dict(self.base, reference_mode="single")
        item = api.save_service(self.svc, service)
        sess = FakeSession(tiny_image())
        with patch.object(api, "_session", return_value=sess):
            result = api.generate(self.svc, {
                "strata_image_profile": item["id"],
                "prompt": "edit", "size": "1024x1024",
                "strata_reference_images": [ref(tiny_image()), ref(tiny_image())],
            })
        self.assertTrue(sess.calls[0][0].endswith("/images/edits"))
        self.assertEqual(len(sess.calls[0][1]["files"]), 1)
        self.assertEqual(result["strata"]["reference_count"], 1)

    def test_unsupported_reference_silently_ignored(self):
        item = api.save_service(self.svc, dict(self.base, reference_mode="none"))
        sess = FakeSession(tiny_image())
        with patch.object(api, "_session", return_value=sess):
            result = api.generate(self.svc, {
                "strata_image_profile": item["id"], "prompt": "test",
                "size": "1024x1024", "strata_reference_images": [ref(tiny_image())],
            })
        self.assertTrue(sess.calls[0][0].endswith("/images/generations"))
        self.assertEqual(result["strata"]["reference_count"], 0)

    def test_bad_endpoint_and_proxy_rejected(self):
        with self.assertRaises(api.ImageServiceError):
            api.save_service(self.svc, dict(self.base, base_url="https://api.example/v1/images/generations"))
        with self.assertRaises(api.ImageServiceError):
            api.save_service(self.svc, dict(self.base, proxy=True, proxy_url="file:///secret"))

    def test_proxy_url_check_does_not_resolve_dns_locally(self):
        with patch.object(api.socket, "getaddrinfo", side_effect=AssertionError("DNS leak")):
            self.assertTrue(api._is_public_address("https://cdn.example.com/image.png", through_proxy=True))
            self.assertFalse(api._is_public_address("https://127.0.0.1/image.png", through_proxy=True))

    def test_real_local_http_provider(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        image = tiny_image()
        calls = []
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                calls.append((self.path, self.headers.get("Authorization"), json.loads(raw)))
                body = json.dumps({"data":[{"b64_json": base64.b64encode(image).decode()}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        import json
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        t = Thread(target=server.serve_forever,daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        entry = api.save_service(self.svc, dict(self.base,
            base_url=f"http://127.0.0.1:{server.server_port}/v1"))
        result = api.generate(self.svc, {"strata_image_profile":entry["id"],
                "prompt":"a test","size":"1024x1024"})
        self.assertEqual(result["strata"]["provider"],"api")
        self.assertEqual(calls[0][0],"/v1/images/generations")
        self.assertEqual(calls[0][1],"Bearer test-api-key")
        self.assertEqual(calls[0][2]["model"],"custom-model")

    def test_discover_models_live_and_reuse_saved_key(self):
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        seen = []
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization")))
                raw = json.dumps({"object": "list", "data": [
                    {"id": "gpt-4.1", "name": "GPT 4.1"},
                    {"id": "flux.1-dev", "name": "FLUX 1 Dev"},
                    {"id": "dall-e-3"},
                    {"id": "gpt-4.1"}
                ]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/v1"
        result = api.discover_models(self.svc, {
            "base_url": base, "api_key": "fresh-key", "proxy": False
        })
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["models"][0]["id"], "dall-e-3")
        self.assertTrue(result["models"][0]["image_likely"])
        self.assertFalse(result["models"][-1]["image_likely"])
        saved = api.save_service(self.svc, dict(self.base, base_url=base))
        from_saved = api.discover_models(self.svc, {
            "id": saved["id"], "base_url": base, "api_key": "", "proxy": False
        })
        self.assertEqual(from_saved["models"], result["models"])
        self.assertEqual(seen, [("/v1/models", "Bearer fresh-key"),
                                ("/v1/models", "Bearer test-api-key")])
        self.assertNotIn("fresh-key", str(result))
        self.assertNotIn("test-api-key", str(from_saved))

    def test_discover_model_error_and_input_validation(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaisesRegex(api.ImageProviderError, "404"):
            api.discover_models(self.svc, {
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "api_key": "test", "proxy": False
            })
        with self.assertRaises(api.ImageServiceError):
            api.discover_models(self.svc, {
                "base_url": "file:///etc/passwd", "proxy": False
            })
        with self.assertRaises(api.ImageServiceError):
            api.discover_models(self.svc, {
                "base_url": "https://api.test/v1", "proxy": True,
                "proxy_url": "file:///etc"
            })
        with self.assertRaises(api.ImageServiceError):
            api.discover_models(self.svc, {
                "id": "api-doesnotexist", "base_url": "https://api.test/v1",
                "proxy": False
            })

    def test_changed_base_cannot_reuse_saved_secret(self):
        entry = api.save_service(self.svc, self.base)
        with self.assertRaisesRegex(api.ImageServiceError, "Base URL changed"):
            api.discover_models(self.svc, {
                "id": entry["id"], "base_url": "https://other.example.test/v1",
                "api_key": "", "proxy": False
            })
        with self.assertRaisesRegex(api.ImageServiceError, "Base URL changed"):
            api.save_service(self.svc, {
                **self.base, "id": entry["id"],
                "base_url": "https://other.example.test/v1", "api_key": ""
            })

    def test_discover_handles_gateway_models_fallback(self):
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        class Gateway(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                content = json.dumps({"models":["custom-image-model", "unknown-model"]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        result = api.discover_models(self.svc, {
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "proxy": False
        })
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["models"][0]["id"], "custom-image-model")
        self.assertFalse(result["models"][1]["image_likely"])

    def test_api_catalog_uses_provider_and_model_name(self):
        item = api.save_service(self.svc, dict(self.base,
            name="鑫旺Neko", model="image-v2"))
        label = api.catalog(self.svc)[0]
        self.assertEqual(label["id"], item["id"])
        self.assertEqual(label["name"], "鑫旺Neko-[image-v2]")

    def test_upscale_is_manual_for_api_and_preserves_original(self):
        fake_backend = SimpleNamespace(cfg={"upscaler": {"enabled": True, "exe": "mock"}})
        self.svc.images = fake_backend
        item = api.save_service(self.svc, self.base)
        sess = FakeSession(tiny_image())
        upscaled = io.BytesIO()
        Image.new("RGB", (32, 32), (120, 40, 30)).save(upscaled, format="PNG")
        with patch.object(api, "_session", return_value=sess):
            with patch("serve.upscale._upscale_one", return_value=(upscaled.getvalue(), 0.3)) as upscale:
                result = api.generate(self.svc, {
                    "strata_image_profile": item["id"], "prompt": "draw",
                    "size": "1024x1024", "strata_upscale": "4x",
                })
                self.assertEqual(upscale.call_count, 1)
        self.assertTrue(result["strata"]["upscale_applied"])
        self.assertEqual(result["size"], "32x32")
        self.assertEqual(result["strata"]["upscale_output_size"], "32x32")
        self.assertEqual(len(result["strata"]["upscale_original_files"]), 1)
        folder = self.svc.session_v1.root / "generated-images"
        original = result["strata"]["upscale_original_files"][0]
        self.assertTrue((folder / original).is_file())
        self.assertTrue((folder / result["strata"]["image_file"]).is_file())

    def test_api_upscale_failure_keeps_output(self):
        self.svc.images = SimpleNamespace(cfg={"upscaler": {"enabled": True, "exe": "mock"}})
        item = api.save_service(self.svc, self.base)
        sess = FakeSession(tiny_image())
        with patch.object(api, "_session", return_value=sess):
            with patch("serve.upscale._upscale_one", side_effect=RuntimeError("upscale unavailable")):
                result = api.generate(self.svc, {
                    "strata_image_profile": item["id"], "prompt": "draw",
                    "size": "1024x1024", "strata_upscale": "4x",
                })
        self.assertFalse(result["strata"]["upscale_applied"])
        self.assertIn("upscale unavailable", result["strata"]["upscale_error"])
        self.assertEqual(result["size"], "1024x1024")
        self.assertEqual(len(result["data"]), 1)

    def test_image_task_status(self):
        from serve import image_task_status as status
        task = "img-" + "a" * 24
        self.assertEqual(status.snapshot(task)["state"], "unknown")
        status.mark(task, "正在请求 API", provider="api")
        self.assertEqual(status.snapshot(task)["phase"], "正在请求 API")
        status.mark(task, "已完成", provider="api", state="done")
        self.assertEqual(status.snapshot(task)["state"], "done")
        self.assertEqual(status.snapshot("garbage")["state"], "unknown")
        local_task = "img-" + "b" * 24
        gen = SimpleNamespace(status=lambda: {"step":3,"steps":8})
        status.mark(local_task, "等待本地生成任务", provider="local")
        self.assertNotIn("step", status.snapshot(local_task, gen=gen))
        status.mark(local_task, "本地模型生成中", provider="local")
        self.assertEqual(status.snapshot(local_task, gen=gen)["step"], 3)

    def test_chat_tool_uses_selected_remote_service(self):
        from serve.character_cards import CharacterStore
        from serve.image_tools import ChatImageHub, NAME
        item = api.save_service(self.svc, self.base)
        cards = CharacterStore(self.svc.session_v1.root.parent / "character")
        cards.set_global({
            "user_name": "", "user_description": "", "default_role": "stateless",
            "chat_image_profile": item["id"],
            "chat_image_settings": {
                "lora_id": "none", "height": 1024, "width": 1024, "upscale": "off", "steps": None,
            }
        }, allowed_image_profiles={item["id"]},
           image_profile_configs={item["id"]: {"family": "api", "max_side":1536, "sizes":"standard"}})
        self.svc.images = None
        self.svc.image_profiles = {}
        hub = ChatImageHub(self.svc)
        self.assertEqual(hub.remote_id, item["id"])
        self.assertIn(NAME, hub.routes())
        fake_result = {"strata": {"image_file": "abc.png"}}
        with patch.object(api, "generate", return_value=fake_result) as call:
            output = hub.call(NAME, {"prompt": "draw a cat", "size": "768x768"})
        self.assertTrue(output["ok"], output["text"])
        self.assertEqual(output["image_file"], "abc.png")
        self.assertEqual(call.call_args.kwargs["ident"], item["id"])
        self.assertEqual(call.call_args.args[1]["size"], "1024x1024")


if __name__ == "__main__":
    unittest.main()
