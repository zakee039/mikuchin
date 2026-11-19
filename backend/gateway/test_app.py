"""Network contract tests against a fake official PolyStrata (no models/paid calls).

Run from the repository root: python -m unittest discover -s backend/gateway -v
"""
from __future__ import annotations

import base64
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

try:
    from .app import GatewayServer
    from .conversations import ConversationStore
    from .characters import CharacterStore
except ImportError:
    from app import GatewayServer
    from conversations import ConversationStore
    from characters import CharacterStore


class FakeOfficial(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen = []
    lock = threading.Lock()
    hold_second_event = False
    release_second_event = threading.Event()
    second_event_sent = threading.Event()
    def log_message(self, *_args):
        pass

    def send_bytes(self, status, payload, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer official-test-secret":
            self.send_bytes(401, b'{"error":"wrong upstream key"}')
            return
        if self.path == "/health":
            self.send_bytes(200, b'{"status":"ok"}')
        elif self.path == "/v1/models":
            self.send_bytes(200, b'{"data":[{"id":"official-model"}]}')
        else:
            self.send_bytes(404, b'{"error":"not found"}')

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size))
        with self.lock:
            self.seen.append((self.path, payload, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer official-test-secret":
            self.send_bytes(401, b'{"error":"wrong upstream key"}')
            return
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(b'data: {"delta":"first"}\n\n')
            self.wfile.flush()
            if FakeOfficial.hold_second_event:
                FakeOfficial.release_second_event.wait(timeout=3)
            else:
                time.sleep(.22)
            self.wfile.write(b'data: {"delta":"second"}\n\n')
            self.wfile.flush()
            FakeOfficial.second_event_sent.set()
        else:
            self.send_bytes(200, json.dumps({"reply":payload.get("messages",[]),
                                              "upstream":"unmodified"}).encode())


class GatewayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.TemporaryDirectory()
        cls.store = ConversationStore(cls.data.name)
        cls.cards = CharacterStore(Path(cls.data.name) / "character")
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeOfficial)
        cls.upstream.daemon_threads = True
        cls.gateway = GatewayServer(("127.0.0.1", 0), api_key="client-test-secret",
                                    upstream_key="official-test-secret",
                                    upstream_host="127.0.0.1",
                                    upstream_port=cls.upstream.server_address[1],
                                    conversations=cls.store, characters=cls.cards)
        cls.threads = []
        for server in (cls.upstream, cls.gateway):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.gateway, cls.upstream):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=2)
        cls.data.cleanup()

    def request(self, method, path, *, payload=None, key="client-test-secret", origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.gateway.server_address[1], timeout=5)
        headers = {"Authorization": "Bearer " + key} if key else {}
        if origin is not None:
            headers["Origin"] = origin
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def test_health_and_native_models_endpoint(self):
        status, data = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)["official_polystrata_reachable"])
        status, data = self.request("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["data"][0]["id"], "official-model")

    def test_unauthorized_and_foreign_origin(self):
        self.assertEqual(self.request("GET", "/v1/models", key=None)[0], 401)
        self.assertEqual(self.request("GET", "/v1/models", key="wrong")[0], 401)
        self.assertEqual(self.request("GET", "/v1/models", origin="https://evil.example")[0], 403)
        local_origin = f"http://127.0.0.1:{self.gateway.server_address[1]}"
        self.assertEqual(self.request("GET", "/v1/models", origin=local_origin)[0], 200)

    def test_private_routes_not_forwarded(self):
        for path in ("/slots/0?action=restore", "/v1/mikuchin/image-jobs", "/config"):
            self.assertEqual(self.request("GET", path)[0], 404, path)
        self.assertEqual(self.request("POST", "/unload", payload={})[0], 404)
        self.assertEqual(self.request("GET", "/v1/strata/sessions")[0], 200)

    def test_unported_mikuchin_semantics_fail_explicitly(self):
        for key in ("strata_image_tool", "answer_budget_tokens"):
            status, result = self.request("POST", "/v1/chat/completions",
                                          payload={"messages":[], key: "x"})
            self.assertEqual(status, 501, key)
            self.assertIn(key.encode(), result)

    def test_legacy_session_metadata_stripped_but_complete_history_forwarded(self):
        ident="a" * 32
        original={"strata_session_id":ident,"mikuchin_stateless":True,
                  "messages":[{"role":"user","content":"latest turn"}]}
        status,data=self.request("POST","/v1/chat/completions",payload=original)
        self.assertEqual(status,200)
        sent=FakeOfficial.seen[-1][1]
        self.assertNotIn("strata_session_id",sent)
        self.assertNotIn("mikuchin_stateless",sent)
        self.assertEqual(sent["messages"],original["messages"])
        bad={"messages":[],"strata_session_id":"../bad"}
        self.assertEqual(self.request("POST","/v1/chat/completions",payload=bad)[0],400)
        self.assertEqual(self.request("POST","/v1/chat/completions",payload={
            "messages":[],"mikuchin_stateless":False})[0],400)

    def test_new_session_crud_and_sampling_are_separate_from_upstream(self):
        ident="f" * 32
        base="/v1/strata/sessions"
        message={"role":"user","text":"A fresh native conversation","time":1234}
        status,data=self.request("POST",base,payload={"id":ident,"web_messages":[message]})
        self.assertEqual(status,200)
        self.assertTrue(json.loads(data)["saved"])
        status,data=self.request("GET",base+"/"+ident)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(data)["web_messages"],[message])
        self.assertEqual(json.loads(data)["title"],"A fresh native conversation")
        self.assertTrue(any(entry["id"]==ident for entry in
            json.loads(self.request("GET",base)[1])["sessions"]))

        sampling={"thinking":"low","budget":1024,"temperature":.8,"top_p":.95,
                  "top_k":20,"max":"","seed":"","show":True,"esp":True,"mcp":False}
        self.assertEqual(self.request("POST",base+"/"+ident,payload={
            "action":"sampling","sampling":sampling})[0],200)
        self.assertEqual(self.request("POST",base+"/"+ident,payload={
            "action":"rename","title":"Renamed chat"})[0],200)
        self.assertEqual(self.request("POST",base+"/"+ident,payload={
            "action":"pin","pinned":True})[0],200)
        saved=json.loads(self.request("GET",base+"/"+ident)[1])
        self.assertEqual(saved["sampling"],sampling)
        self.assertTrue(saved["pinned"])
        self.assertEqual(saved["title"],"Renamed chat")
        self.assertEqual(saved["web_messages"],[message])

        self.assertEqual(self.request("POST","/v1/strata/sampling-default",payload={
            "sampling":sampling})[0],200)
        self.assertEqual(json.loads(self.request("GET","/v1/strata/sampling-default")[1])["sampling"],sampling)
        self.assertEqual(self.request("POST",base+"/"+ident,payload={
            "action":"lock_kv","locked":True})[0],410)

        self.assertEqual(self.request("DELETE",base+"/"+ident)[0],200)
        self.assertEqual(self.request("GET",base+"/"+ident)[0],404)

    def test_invalid_session_requests_cannot_mutate_store(self):
        base="/v1/strata/sessions"
        for request in ({"id":"../bad","web_messages":[]},
                        {"id":"b"*32,"web_messages":{"role":"user"}},
                        {"id":"c"*32,"web_messages":[{"role":"invalid"}]}):
            self.assertEqual(self.request("POST",base,payload=request)[0],400)
        self.assertEqual(self.request("POST","/v1/strata/sampling-default",payload={
            "sampling":{"budget":-10}})[0],400)
        self.assertEqual(self.request("GET",base+"/"+"b"*32)[0],404)

    def test_native_character_card_assignment_freezes_after_first_turn(self):
        endpoint="/v1/strata/characters"
        ident=uuid4().hex
        status,body=self.request("GET",endpoint)
        self.assertEqual(status,200)
        self.assertIn("cards",json.loads(body))
        card={"name":"Test role " + ident[:8],"description":"A thoughtful teacher",
              "lorebook":[{"keys":"winter","content":"Winter break","constant":False}]}
        status,body=self.request("POST",endpoint,payload={"action":"save","card":card})
        self.assertEqual(status,200)
        saved=json.loads(body)["card"]
        self.assertEqual(saved["name"],card["name"])
        self.assertTrue(self.request("POST",endpoint,payload={"action":"assign",
            "session_id":ident,"card_id":saved["id"]})[0]==200)
        self.assertEqual(self.cards.snapshot()["assignments"][ident],saved["id"])
        status,body=self.request("POST",endpoint,payload={"action":"global",
            "global":{"user_name":"Native user","user_description":"Learns AI",
                      "default_role":saved["id"]}})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)["global"]["default_role"],saved["id"])

        # No silent role reassignment once a real chat turn has been saved.
        self.store.save_messages(ident,[{"role":"user","text":"Hello"}])
        self.assertEqual(self.request("POST",endpoint,payload={"action":"assign",
            "session_id":ident,"card_id":"ordinary"})[0],400)
        self.assertEqual(self.cards.snapshot()["assignments"][ident],saved["id"])
        self.assertEqual(self.request("DELETE","/v1/strata/sessions/"+ident)[0],200)
        self.assertNotIn(ident,self.cards.snapshot()["assignments"])
        self.assertEqual(self.request("POST",endpoint,payload={"action":"delete","id":saved["id"]})[0],200)

    def test_character_worldbook_markdown_and_one_time_workflow(self):
        endpoint="/v1/strata/characters"
        ident=uuid4().hex
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"my-world.md"
            path.write_text("# 星星\n星星课堂在晚上开设。",encoding="utf-8")
            flow=Path(temp)/"profile.md"
            flow.write_text("## 初始化\n首次见面欢迎\n## 全程行为约束\n保持简洁",encoding="utf-8")
            card={"name":"World test " + ident[:8],
                  "sources":[{"kind":"file","path":str(path),"recursive":False}],
                  "workflow_path":str(flow)}
            status,data=self.request("POST",endpoint,payload={"action":"save","card":card})
            self.assertEqual(status,200)
            cid=json.loads(data)["card"]["id"]
            self.assertEqual(self.request("POST",endpoint,payload={"action":"assign",
                "session_id":ident,"card_id":cid})[0],200)
            result=json.loads(self.request("POST",endpoint,payload={"action":"retrieve",
                "session_id":ident,"query":"星星课堂"})[1])
            self.assertIn("晚上",result["snippets"][0]["content"])
            initial=json.loads(self.request("POST",endpoint,payload={"action":"prepare_workflow",
                "session_id":ident,"first_user_turn":True})[1])
            self.assertTrue(initial["initial_pending"])
            self.assertIn("欢迎",initial["sections"]["initial"])
            self.assertEqual(self.request("POST",endpoint,payload={"action":"commit_workflow",
                "session_id":ident})[0],200)
            flow.write_text("## 初始化\n全新规则\n## 全程行为约束\n不修改旧会话",encoding="utf-8")
            old=json.loads(self.request("POST",endpoint,payload={"action":"prepare_workflow",
                "session_id":ident,"first_user_turn":False})[1])
            self.assertEqual(old["sha256"],initial["sha256"])
            self.assertFalse(old["initial_pending"])
            self.assertEqual(self.request("POST",endpoint,payload={"action":"delete","id":cid})[0],200)

    def test_character_reference_image_requires_auth_and_has_valid_png(self):
        from PIL import Image
        endpoint="/v1/strata/characters"
        name="PNG Test " + uuid4().hex[:8]
        card=json.loads(self.request("POST",endpoint,payload={"action":"save",
            "card":{"name":name}})[1])["card"]
        buf=io.BytesIO()
        Image.new("RGB",(40,20),"white").save(buf,format="PNG")
        encoded=base64.b64encode(buf.getvalue()).decode()
        self.assertEqual(self.request("POST",endpoint,payload={"action":"reference_upload",
            "id":card["id"],"data":encoded})[0],200)
        url=endpoint+"/reference/"+card["id"]
        self.assertEqual(self.request("GET",url,key=None)[0],401)
        status,png=self.request("GET",url)
        self.assertEqual(status,200)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(self.request("POST",endpoint,payload={"action":"reference_remove",
            "id":card["id"]})[0],200)
        self.assertNotEqual(self.request("GET",url)[0],200)
        self.assertEqual(self.request("POST",endpoint,payload={"action":"delete","id":card["id"]})[0],200)

    def test_conversation_store_survives_restart_and_simultaneous_clients(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ConversationStore(directory)
            def write(index):
                ident=f"{index+1:032x}"
                store.save_messages(ident,[{"role":"user","text":f"new session {index}"}])
                return ident
            with ThreadPoolExecutor(max_workers=8) as executor:
                ids=list(executor.map(write,range(24)))
            self.assertEqual(len(store.listing()),24)
            reopened=ConversationStore(directory)
            self.assertEqual(len(reopened.listing()),24)
            for index,ident in enumerate(ids):
                self.assertEqual(reopened.get(ident)["web_messages"][0]["text"],
                                 f"new session {index}")
            self.assertTrue(reopened.delete(ids[0])["deleted"])
            self.assertEqual(len(store.listing()),23)

    def test_sampling_before_first_turn_preserves_settings_and_gains_first_title(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ConversationStore(directory)
            ident="d" * 32
            first=store.change(ident,"sampling",{"sampling":{"thinking":"high","budget":16384}})
            self.assertEqual(first["title"],"New chat")
            store.save_messages(ident,[{"role":"user","text":"The first user turn"}])
            second=store.get(ident)
            self.assertEqual(second["title"],"The first user turn")
            self.assertEqual(second["sampling"],{"thinking":"high","budget":16384})
            store.change(ident,"rename",{"title":"Hand-picked title"})
            store.save_messages(ident,[{"role":"user","text":"Edited first turn"}])
            self.assertEqual(store.get(ident)["title"],"Hand-picked title")

    def test_standard_chat_and_upstream_key_isolation(self):
        before = len(FakeOfficial.seen)
        messages = [{"role":"user","content":"only native backend"}]
        status, data = self.request("POST", "/v1/chat/completions",
                                    payload={"model":"official-model", "messages":messages})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["reply"], messages)
        self.assertEqual(len(FakeOfficial.seen), before + 1)
        self.assertEqual(FakeOfficial.seen[-1][2], "Bearer official-test-secret")

    def test_parallel_requests_stay_isolated(self):
        def one(n):
            status, data = self.request("POST", "/v1/chat/completions",
                                        payload={"messages":[{"role":"user","content":str(n)}]})
            return status, json.loads(data)["reply"][0]["content"]
        with ThreadPoolExecutor(max_workers=6) as executor:
            outcome = list(executor.map(one, range(12)))
        self.assertEqual(outcome, [(200,str(n)) for n in range(12)])

    def test_sse_first_event_is_not_buffered_until_last_event(self):
        FakeOfficial.hold_second_event = True
        FakeOfficial.release_second_event.clear()
        FakeOfficial.second_event_sent.clear()
        conn = http.client.HTTPConnection("127.0.0.1", self.gateway.server_address[1], timeout=5)
        try:
            body = json.dumps({"messages":[], "stream":True}).encode()
            conn.request("POST", "/v1/chat/completions", body=body,
                         headers={"Authorization":"Bearer client-test-secret", "Content-Type":"application/json"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
            chunk = response.read1(65536)
            self.assertIn(b'first', chunk)
            self.assertFalse(FakeOfficial.second_event_sent.is_set(),
                             "Gateway must forward first SSE event before the upstream sends another")
            FakeOfficial.release_second_event.set()
            rest = response.read()
            self.assertIn(b'second', rest)
        finally:
            FakeOfficial.release_second_event.set()
            FakeOfficial.hold_second_event = False
            conn.close()

    def test_no_default_auth_secrets(self):
        with self.assertRaises(ValueError):
            GatewayServer(("127.0.0.1",0), api_key="", upstream_key="secret",
                          upstream_host="127.0.0.1", upstream_port=15240)
        with self.assertRaises(ValueError):
            GatewayServer(("127.0.0.1",0), api_key="valid", upstream_key="secret",
                          upstream_host="192.168.0.10", upstream_port=15240)

    def test_explicit_origin_allows_preflight_and_forwards_model_list(self):
        server = GatewayServer(("127.0.0.1", 0), api_key="client-test-secret",
                               upstream_key="official-test-secret", upstream_host="127.0.0.1",
                               upstream_port=self.upstream.server_address[1],
                               allowed_origins=("https://trusted.example",))
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=4)
            conn.request("OPTIONS", "/v1/models", headers={
                "Origin":"https://trusted.example", "Access-Control-Request-Method":"GET"})
            res = conn.getresponse()
            self.assertEqual(res.status, 204)
            self.assertEqual(res.getheader("Access-Control-Allow-Origin"), "https://trusted.example")
            res.read()
            conn.request("GET", "/v1/models", headers={
                "Authorization":"Bearer client-test-secret", "Origin":"https://trusted.example"})
            res = conn.getresponse()
            self.assertEqual(res.status, 200)
            self.assertEqual(res.getheader("Access-Control-Allow-Origin"), "https://trusted.example")
            res.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            runner.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
