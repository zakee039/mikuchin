import base64
import io
import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from backend.gateway import image_providers as p
from backend.gateway.test_image_network_stages import running


class ApiCompatTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=SimpleNamespace(root=Path(self.temp.name))
        buf=io.BytesIO(); Image.new("RGB",(24,16),"red").save(buf,format="JPEG")
        self.jpeg=buf.getvalue(); self.b64=base64.b64encode(self.jpeg).decode()
        self.requests=[]
        self.content_type="application/json"; self.status=200
        self.response=json.dumps({"data":[{"b64_json":self.b64}]}).encode()

    def server(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                chunks=[]; lengths=[]
                if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                    while True:
                        line=self.rfile.readline(); n=int(line.strip().split(b";",1)[0],16)
                        if not n:
                            assert self.rfile.readline()==b"\r\n"
                            break
                        lengths.append(n); chunks.append(self.rfile.read(n)); assert self.rfile.read(2)==b"\r\n"
                else:
                    chunks.append(self.rfile.read(int(self.headers["Content-Length"])))
                owner.chunk_lengths=lengths
                owner.requests.append((self.path,dict(self.headers),b"".join(chunks)))
                self.send_response(owner.status); self.send_header("Content-Type",owner.content_type)
                self.send_header("Content-Length",str(len(owner.response))); self.end_headers(); self.wfile.write(owner.response)
        return ThreadingHTTPServer(("127.0.0.1",0),Handler)

    def invoke(self, refs=False, **overrides):
        with running(self.server()) as port:
            service=dict(id="api-compat-test",name="test",api_key="OFFLINE_SECRET",base_url=f"http://127.0.0.1:{port}/v1",model="fake",sizes="standard",reference_mode="multi",negative=False,seed=False,steps=False,proxy=False,connect_timeout_seconds=2,timeout_seconds=2)
            service.update(overrides)
            req=dict(prompt="offline prompt",size="1024x1024")
            if refs: req["strata_reference_images"]=["data:image/jpeg;base64,"+self.b64]*int(refs)
            with patch.object(p,"get",return_value=service): return p.generate(self.store,req)

    def test_defaults_and_preserves_original_jpeg(self):
        self.invoke(refs=True)
        path,headers,body=self.requests[0]
        self.assertTrue(path.endswith("/images/edits")); self.assertIn(self.jpeg,body)
        self.assertIn(b'name="image[]"',body); self.assertIn(b"image/jpeg",body)
        self.assertIn(b'name="quality"\r\n\r\nmedium',body)
        self.assertIn(b'name="output_format"\r\n\r\njpeg',body)
        self.assertEqual(headers.get("Transfer-Encoding"), "chunked")
        self.assertNotIn("Content-Length",headers)
        self.assertNotIn(b'name="n"',body)
        self.assertIn(b'filename="photo.jpg"',body)
        self.assertTrue(headers["Content-Type"].startswith("multipart/form-data; boundary=----MikuCamera"))
        self.assertEqual(len(self.requests),1)

    def test_large_two_reference_chunks(self):
        import random
        from email.parser import BytesParser
        from email.policy import default
        rng=random.Random(42)
        im=Image.frombytes("RGB",(512,512),rng.randbytes(512*512*3))
        buf=io.BytesIO(); im.save(buf,format="JPEG",quality=95); raw=buf.getvalue()
        self.jpeg=raw;self.b64=base64.b64encode(raw).decode()
        self.invoke(refs=2)
        _,headers,body=self.requests[0]
        msg=BytesParser(policy=default).parsebytes(("Content-Type: "+headers["Content-Type"]+"\r\nMIME-Version: 1.0\r\n\r\n").encode()+body)
        parts=list(msg.iter_parts())
        self.assertEqual([v.get_param("name",header="content-disposition") for v in parts],["model","prompt","quality","size","output_format","image[]","image[]"])
        self.assertEqual([v.get_filename() for v in parts[-2:]],["photo.jpg","reference.jpg"])
        self.assertTrue(all(v.get_payload(decode=True)==raw for v in parts[-2:]))
        self.assertIn(65536,self.chunk_lengths);self.assertLessEqual(max(self.chunk_lengths),65536)
        self.assertEqual(len(self.requests),1)

    def test_fixed_upload_option(self):
        self.invoke(refs=True,upload_mode="fixed")
        _,headers,body=self.requests[0]
        self.assertEqual(int(headers["Content-Length"]),len(body))
        self.assertNotIn("Transfer-Encoding",headers);self.assertNotIn(b'name="n"',body)
        self.assertIn(self.jpeg,body)

    def test_default_omits_optional_fields(self):
        self.invoke(quality="default",output_format="default")
        body=json.loads(self.requests[0][2]); self.assertNotIn("quality",body); self.assertNotIn("output_format",body)

    def test_direct_jpeg_is_normalized_for_gallery(self):
        self.content_type="image/jpeg"; self.response=self.jpeg
        result=self.invoke(); self.assertTrue(base64.b64decode(result["data"][0]["b64_json"]).startswith(b"\x89PNG"))

    def test_alternate_base64_and_data_url(self):
        for data in ({"images":[{"base64":self.b64}]},{"image":{"image_url":"data:image/jpeg;base64,"+self.b64}},{"b64":self.b64}):
            self.response=json.dumps(data).encode(); self.assertEqual(self.invoke()["output_format"],"png")

    def test_provider_error_preserves_tool_payload_except_key(self):
        self.status=400; self.response=json.dumps({"error":{"message":"OFFLINE_SECRET {\"referenced_image_ids\":[\"file_secret1234\"],\"prompt\":\"private text\"}","code":"bad_request"}}).encode()
        with self.assertRaises(p.ImageProviderError) as exc: self.invoke()
        text=str(exc.exception); self.assertIn("HTTP 400",text); self.assertIn("bad_request",text); self.assertNotIn("OFFLINE_SECRET",text); self.assertIn("private text",text); self.assertIn("file_secret",text)

    def test_long_provider_error_is_not_truncated(self):
        self.status=400; msg="diagnostic "*600+"TAIL_MARKER"
        self.response=json.dumps({"error":{"message":msg}}).encode()
        with self.assertRaises(p.ImageProviderError) as exc: self.invoke()
        self.assertIn(msg,str(exc.exception))

    def test_plain_text_http_error_retained(self):
        self.status=502; self.content_type="text/plain"; self.response=b"upstream unavailable"
        with self.assertRaisesRegex(p.ImageProviderError,"HTTP 502: upstream unavailable"): self.invoke()

    def test_service_settings_roundtrip(self):
        saved=p.save_service(self.store,{"name":"test","base_url":"https://example.com/v1","model":"fake","api_key":"OFFLINE_SECRET"})
        self.assertEqual((saved["quality"],saved["output_format"],saved["connect_timeout_seconds"],saved["timeout_seconds"]),("medium","jpeg",30,300))
        self.assertNotIn("api_key",saved)
        self.assertEqual(saved["upload_mode"],"chunked")
        updated=p.save_service(self.store,{**saved,"quality":"default","output_format":"webp"})
        self.assertEqual((updated["quality"],updated["output_format"]),("default","webp"))
        self.assertEqual(p.get(self.store,saved["id"])["api_key"],"OFFLINE_SECRET")
