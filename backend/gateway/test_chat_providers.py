"""Loopback-only integration tests for online chat and frozen turn routing."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from backend.gateway import chat_providers as p
from backend.gateway.chat_turn_service import TurnCoordinator
from backend.gateway.chat_turns import ChatTurnStore
from backend.gateway.conversations import ConversationStore
from backend.gateway.request_monitor import RequestMonitor
from backend.gateway.test_image_network_stages import running

class ChatProviders(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.requests=[];self.status=200;self.mode="text"
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                outer.requests.append((self.path,None,self.headers.get("Authorization")))
                body=json.dumps({"data":[{"id":"text-only"},{"id":"multimodal","capabilities":{"vision":True,"tool_calling":True,"reasoning":False}}, {"id":"text-only"},{"id":"unknown","description":"vision reasoning", "capabilities":{"vision":"yes"}}, {"id":"other","api_key":"DO_NOT_RETURN"}]}).encode()
                self.send_response(outer.status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                req=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path,req,self.headers.get("Authorization")))
                if outer.status!=200:
                    body=b'{"error":{"message":"private mock diagnostic"}}';typ="application/json"
                else:
                    if outer.mode=="tool":
                        msg={"role":"assistant","content":"","tool_calls":[{"id":"call_offline","type":"function","function":{"name":"generate_image","arguments":'{"prompt":"a tree"}'}}]};finish="tool_calls"
                    else:msg={"role":"assistant","content":"mock answer"};finish="stop"
                    if req["stream"]:
                        delta={**msg};delta.pop("role",None)
                        if delta.get("tool_calls"):delta["tool_calls"][0]["index"]=0
                        events=[{"choices":[{"index":0,"delta":delta,"finish_reason":None}]},{"choices":[{"index":0,"delta":{},"finish_reason":finish}]}]
                        body=("".join("data: "+json.dumps(e)+"\n\n" for e in events)+"data: [DONE]\n\n").encode();typ="text/event-stream"
                    else:body=json.dumps({"choices":[{"message":msg,"finish_reason":finish}]}).encode();typ="application/json"
                self.send_response(outer.status);self.send_header("Content-Type",typ);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.ctx=running(self.server);port=self.ctx.__enter__();self.addCleanup(self.ctx.__exit__,None,None,None)
        self.cfg={"name":"mock","model":"actual-cloud-model","base_url":f"http://127.0.0.1:{port}/v1","api_key":"FAKE_OFFLINE_CHAT_KEY","tools":True,"vision":True,"stream":True}
        self.public=p.save(self.root,self.cfg);self.ref={k:self.public[k] for k in ("id","revision")}
        self.monitor=RequestMonitor()
    def test_registry_encrypted_windows_and_revision_pinned(self):
        self.assertNotIn("api_key",self.public);self.assertNotIn("protected_key",self.public)
        import os
        if os.name=="nt":self.assertNotIn("FAKE_OFFLINE_CHAT_KEY",(self.root/"chat-api-services.json").read_text())
        with self.assertRaises(p.ChatProviderError):p.save(self.root,{**self.cfg,"id":self.ref["id"],"api_key":"","base_url":"https://other.example/v1"})
        changed=p.save(self.root,{**self.cfg,"id":self.ref["id"],"api_key":"","model":"changed-model"})
        with self.assertRaises(p.ChatProviderError):p.resolve(self.root,self.ref)
        self.assertEqual(p.resolve(self.root,{"id":changed["id"],"revision":changed["revision"]})["model"],"changed-model")
    def test_native_stream_and_no_local_parameters(self):
        self.mode="tool";payload={"model":"local","messages":[{"role":"user","content":"draw"}],"tools":[{"type":"function","function":{"name":"generate_image"}}],"tool_choice":"auto","strata_mcp":True,"top_k":20,"reasoning_budget_tokens":4096}
        obj=p.complete(self.root,self.ref,payload,self.monitor,lambda d:None)
        path,wire,key=self.requests[0];self.assertEqual(path,"/v1/chat/completions");self.assertEqual(key,"Bearer FAKE_OFFLINE_CHAT_KEY");self.assertEqual(wire["model"],"actual-cloud-model");self.assertTrue(wire["stream"]);self.assertNotIn("strata_mcp",wire);self.assertNotIn("top_k",wire);self.assertNotIn("reasoning_budget_tokens",wire);self.assertEqual(obj["choices"][0]["finish_reason"],"tool_calls");self.assertEqual(len(self.requests),1)
    def test_nonstream_and_no_replay(self):
        payload={"messages":[{"role":"user","content":"hi"}]}
        obj=p.complete(self.root,self.ref,payload,self.monitor);self.assertEqual(obj["choices"][0]["message"]["content"],"mock answer")
        self.status=400
        with self.assertRaisesRegex(p.ChatProviderError,"HTTP 400"):p.complete(self.root,self.ref,payload,self.monitor)
        self.assertEqual(len(self.requests),2)
    def test_capabilities(self):
        pub=p.save(self.root,{**self.cfg,"id":self.ref["id"],"vision":False,"tools":False,"stream":False});ref={k:pub[k] for k in ("id","revision")}
        with self.assertRaisesRegex(p.ChatProviderError,"不支持本次图片输入"):p.complete(self.root,ref,{"messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"data:image/png;base64,abc"}}]}]},self.monitor)
        self.assertEqual(len(self.requests),0)
        p.complete(self.root,ref,{"messages":[{"role":"user","content":"hi"}],"tools":[{}]},self.monitor,lambda d:None)
        self.assertNotIn("tools",self.requests[0][1]);self.assertFalse(self.requests[0][1]["stream"])
    def test_turn_idempotency_and_frozen_route(self):
        c=object.__new__(TurnCoordinator);c.store=ChatTurnStore(self.root);c._lock=threading.Lock();c._conversation_decisions={}
        c.server=SimpleNamespace(characters=None,image_jobs=None,request_monitor=self.monitor)
        req={"session_id":"a"*32,"turn_id":"b"*32,"model":"local-fake","messages":[{"role":"user","content":"hello"}],"chat_profile":self.ref["id"],"chat_revision":self.ref["revision"]}
        with patch.object(c,"_official",side_effect=AssertionError("must not use local")),patch.object(c,"_official_stream",side_effect=AssertionError("must not use local")):
            result=c.submit(req,on_delta=lambda d:None);again=c.submit(req,on_delta=lambda d:None)
        self.assertEqual(result["state"],"text_done");self.assertEqual(result["text"],"mock answer");self.assertEqual(again["text"],result["text"]);self.assertEqual(len(self.requests),1)
        saved=json.loads(c.store.get(req["session_id"],req["turn_id"])["request_json"]);self.assertEqual(saved["_chat_provider"],self.ref);self.assertNotIn("FAKE_OFFLINE_CHAT_KEY",json.dumps(saved));self.assertEqual(c._session_context(req["session_id"],saved),saved["messages"])
    def test_session_selection_persists_and_defaults_local(self):
        store=ConversationStore(self.root);ident="c"*32
        store.save_messages(ident,[{"role":"user","text":"old"}]);self.assertEqual(store.get(ident)["chat_profile"],"local")
        store.change(ident,"chat_profile",{"chat_profile":self.ref["id"],"chat_revision":self.ref["revision"]});self.assertEqual(ConversationStore(self.root).get(ident)["chat_revision"],self.ref["revision"])
        store.save_messages(ident,[{"role":"user","text":"new"}]);self.assertEqual(store.get(ident)["chat_profile"],self.ref["id"])

    def test_gateway_real_authenticated_registry_and_turn(self):
        import http.client
        from backend.gateway.app import GatewayServer
        from backend.gateway.image_jobs import ImageJobStore
        from backend.gateway.characters import CharacterStore
        # No local inference server is listening. Online completion must not
        # depend on it. All outbound calls stay in the fake loopback service.
        gateway=GatewayServer(("127.0.0.1",0),api_key="test-gateway-key",upstream_key="test-upstream-key",upstream_host="127.0.0.1",upstream_port=1,conversations=ConversationStore(self.root),characters=CharacterStore(self.root),image_jobs=ImageJobStore(self.root/"images"),tool_calling_enabled=True)
        with running(gateway) as port:
            try:
                def request(method,path,body=None,key="test-gateway-key"):
                    conn=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
                    try:
                        hdr={"Authorization":"Bearer "+key} if key else {}
                        raw=json.dumps(body).encode() if body is not None else None
                        if raw:hdr["Content-Type"]="application/json"
                        conn.request(method,path,body=raw,headers=hdr);res=conn.getresponse();return res.status,res.read().decode()
                    finally:conn.close()
                path="/v1/mikuchin/chat-api-services"
                self.assertEqual(request("GET",path,key=None)[0],401)
                code,raw=request("GET",path);self.assertEqual(code,200);self.assertNotIn("FAKE_OFFLINE_CHAT_KEY",raw);self.assertNotIn("protected_key",raw)
                session="d"*32;turn="e"*32
                self.assertEqual(request("POST","/v1/strata/sessions/"+session,{"action":"chat_profile","chat_profile":self.ref["id"],"chat_revision":self.ref["revision"]})[0],200)
                req={"session_id":session,"turn_id":turn,"model":"local","chat_profile":self.ref["id"],"chat_revision":self.ref["revision"],"messages":[{"role":"user","content":"hello"}]}
                code,raw=request("POST","/v1/mikuchin/chat/turns/stream",req);self.assertEqual(code,200);self.assertIn("mock answer",raw);self.assertIn("text_done",raw);self.assertEqual(len(self.requests),1)
            finally:gateway.server_close()

    def test_image_followup_uses_original_api_and_original_context(self):
        c=object.__new__(TurnCoordinator);c.store=ChatTurnStore(self.root);c._lock=threading.Lock();c._conversation_decisions={}
        c.server=SimpleNamespace(request_monitor=self.monitor,conversations=SimpleNamespace(get=lambda _: {"web_messages":[{"role":"user","text":"PRIVATE_LATER_LOCAL_MESSAGE"}]}))
        session="f"*32;turn="a"*32
        c.store.create(session,turn,{"model":"actual-cloud-model","messages":[{"role":"user","content":"draw a tree"}],"_chat_provider":self.ref})
        c.store.decision_tool(session,turn,{"name":"generate_image","tool_call_id":"call_tree","arguments":{"prompt":"a tree"}},{"prompt":"a tree"},{"profile":"api-mock","online":True,"require_approval":False})
        with patch.object(c,"_official",side_effect=AssertionError("unexpected local call")):
            self.assertEqual(c._followup(session,turn,"failed",{"type":"image_job_failed"},300),"mock answer")
        wire=self.requests[0][1];self.assertEqual(wire["model"],"actual-cloud-model");self.assertNotIn("PRIVATE_LATER_LOCAL_MESSAGE",json.dumps(wire));self.assertNotIn("tools",wire);self.assertEqual(wire["max_tokens"],300)

    def test_text_only_model_keeps_text_from_historical_images(self):
        pub=p.save(self.root,{**self.cfg,"id":self.ref["id"],"vision":False,"tools":False});ref={k:pub[k] for k in ("id","revision")}
        messages=[{"role":"user","content":[{"type":"text","text":"old description"},{"type":"image_url","image_url":{"url":"data:image/png;base64,PRIVATE_IMAGE"}}]},{"role":"assistant","content":"past answer"},{"role":"user","content":"new text question"}]
        p.complete(self.root,ref,{"messages":messages},self.monitor)
        wire=json.dumps(self.requests[0][1]);self.assertIn("old description",wire);self.assertIn("Historical image not sent",wire);self.assertNotIn("PRIVATE_IMAGE",wire);self.assertIn("new text question",wire)

    def test_discover_unsaved_credentials_and_explicit_metadata(self):
        before=(self.root/"chat-api-services.json").read_bytes()
        result=p.discover(self.root,self.cfg)
        self.assertEqual(self.requests,[("/v1/models",None,"Bearer FAKE_OFFLINE_CHAT_KEY")])
        self.assertEqual(result["models"],[{"id":"text-only","capabilities":{}},{"id":"multimodal","capabilities":{"vision":True,"tools":True,"reasoning":False}},{"id":"unknown","capabilities":{}},{"id":"other","capabilities":{}}])
        self.assertEqual(before,(self.root/"chat-api-services.json").read_bytes())
        self.assertNotIn("DO_NOT_RETURN",json.dumps(result))
    def test_discover_saved_key_only_same_route(self):
        cfg={**self.cfg,"id":self.ref["id"],"api_key":""}
        p.discover(self.root,cfg)
        with self.assertRaises(p.ChatProviderError):p.discover(self.root,{**cfg,"base_url":"https://other.example/v1"})
        with self.assertRaises(p.ChatProviderError):p.discover(self.root,{**cfg,"proxy":True,"proxy_url":"http://127.0.0.1:1"})
        self.assertEqual(len(self.requests),1)
        self.status=401
        with self.assertRaisesRegex(p.ChatProviderError,"HTTP 401"):p.discover(self.root,cfg)
        self.assertEqual(len(self.requests),2)
    def test_output_limit_optional_preserve_followup_limit(self):
        payload={"messages":[{"role":"user","content":"hello"}]}
        p.complete(self.root,self.ref,payload,self.monitor)
        self.assertNotIn("max_tokens",self.requests[-1][1])
        p.complete(self.root,self.ref,{**payload,"max_tokens":256},self.monitor)
        self.assertEqual(self.requests[-1][1]["max_tokens"],256)
        pub=p.save(self.root,{**self.cfg,"id":self.ref["id"],"max_tokens":2048});ref={k:pub[k] for k in ("id","revision")}
        p.complete(self.root,ref,payload,self.monitor)
        self.assertEqual(self.requests[-1][1]["max_tokens"],2048)
