"""Native model-driven image tool contracts; no real model or billable calls."""
from __future__ import annotations
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .app import GatewayServer
    from .conversations import ConversationStore
    from .characters import CharacterStore
    from .image_jobs import ImageJobStore
    from .chat_tool_dispatch import InvalidToolCall, parse_decision, TOOL_SCHEMAS
    from .chat_turns import ChatTurnStore, TurnForbidden
    from . import chat_turn_service as service_module
except ImportError:
    from app import GatewayServer
    from conversations import ConversationStore
    from characters import CharacterStore
    from image_jobs import ImageJobStore
    from chat_tool_dispatch import InvalidToolCall, parse_decision, TOOL_SCHEMAS
    from chat_turns import ChatTurnStore, TurnForbidden
    import chat_turn_service as service_module

SESSION="a"*32
OTHER="b"*32
TURN="c"*32
TURN2="d"*32


def model_decision(name=None, args=None, finish=None):
    if name:
        return {"choices":[{"finish_reason":finish or "tool_calls","message":{
            "role":"assistant","content":None,
            "tool_calls":[{"id":"call_123","type":"function","function":{
                "name":name,"arguments":json.dumps(args if args is not None else {"prompt":"a cat"})}}]}}]}
    return {"choices":[{"finish_reason":finish or "stop","message":{
        "role":"assistant","content":"这是普通文本回答"}}]}


class ToolParser(unittest.TestCase):
    def test_generate(self):
        got=parse_decision(model_decision("generate_image"))
        self.assertEqual(got["name"],"generate_image")
        self.assertEqual(got["arguments"]["prompt"],"a cat")

    def test_edit(self):
        got=parse_decision(model_decision("edit_image",{"instruction":"make eyes larger"}))
        self.assertEqual(got["name"],"edit_image")

    def test_text(self):
        self.assertEqual(parse_decision(model_decision())["kind"],"text")

    def test_untrusted_plain_json_not_a_tool(self):
        fake=model_decision()
        fake["choices"][0]["message"]["content"]='{"name":"generate_image","arguments":{"prompt":"cat"}}'
        self.assertEqual(parse_decision(fake)["kind"],"text")

    def test_multi_call_rejected(self):
        payload=model_decision("generate_image")
        payload["choices"][0]["message"]["tool_calls"].append(dict(payload["choices"][0]["message"]["tool_calls"][0]))
        with self.assertRaises(InvalidToolCall):parse_decision(payload)

    def test_truncated_call_rejected(self):
        with self.assertRaises(InvalidToolCall):
            parse_decision(model_decision("generate_image",finish="length"))

    def test_unknown_function_rejected(self):
        with self.assertRaises(InvalidToolCall):
            parse_decision(model_decision("shell",{"command":"erase C:"}))

    def test_invalid_args_rejected(self):
        for args in ({"prompt":"test","size":"1536x1536"},{"prompt":""},{}):
            with self.subTest(args=args),self.assertRaises(InvalidToolCall):
                parse_decision(model_decision("generate_image",args))

    def test_duplicate_json_keys_rejected(self):
        payload=model_decision("generate_image")
        payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]='{"prompt":"cat","prompt":"dog"}'
        with self.assertRaises(InvalidToolCall):parse_decision(payload)

    def test_only_two_known_tools(self):
        self.assertEqual({s["function"]["name"] for s in TOOL_SCHEMAS},
                         {"generate_image","edit_image"})


class DurableTurns(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ChatTurnStore(self.temp.name)
        self.request={"model":"mock","messages":[{"role":"user","content":"draw a cat"}]}

    def tearDown(self):self.temp.cleanup()

    def test_create_idempotent_and_isolated(self):
        self.assertTrue(self.store.create(SESSION,TURN,self.request))
        self.assertFalse(self.store.create(SESSION,TURN,self.request))
        with self.assertRaises(TurnForbidden):
            self.store.create(OTHER,TURN,self.request)
        with self.assertRaises(TurnForbidden):
            self.store.get(OTHER,TURN)

    def test_non_chargeable_text_replay(self):
        self.store.create(SESSION,TURN,self.request)
        self.assertTrue(self.store.decision_text(SESSION,TURN,"response"))
        self.assertFalse(self.store.decision_text(SESSION,TURN,"second"))
        self.assertEqual(self.store.public(SESSION,TURN)["text"],"response")

    def test_online_requires_one_time_token(self):
        self.store.create(SESSION,TURN,self.request)
        token=self.store.decision_tool(SESSION,TURN,{"name":"generate_image",
            "tool_call_id":"c1","arguments":{"prompt":"red cat"}},
            {"prompt":"red cat","strata_image_profile":"api-pay","size":"512x512"},
            {"profile":"api-pay","online":True})
        self.assertGreater(len(token),30)
        self.assertEqual(self.store.get(SESSION,TURN)["state"],"awaiting_approval")
        self.assertNotIn(token,Path(self.store.path).read_bytes().decode("utf-8","ignore"))
        with self.assertRaises(ValueError):
            self.store.accept_approval(SESSION,TURN,"wrongtoken"*7)
        self.store.accept_approval(SESSION,TURN,token)
        self.assertEqual(self.store.get(SESSION,TURN)["state"],"queued")
        with self.assertRaises(ValueError):self.store.accept_approval(SESSION,TURN,token)

    def test_on_restart_does_not_replay_model(self):
        self.store.create(SESSION,TURN,self.request)
        restored=ChatTurnStore(self.temp.name)
        self.assertEqual(restored.get(SESSION,TURN)["state"],"decision_error")

    def test_cancel_online_without_job(self):
        self.store.create(SESSION,TURN,self.request)
        self.store.decision_tool(SESSION,TURN,{"name":"generate_image",
            "tool_call_id":"c1","arguments":{"prompt":"cat"}}, {"prompt":"cat"},
            {"profile":"api-pay","online":True})
        self.assertTrue(self.store.cancel_approval(SESSION,TURN))
        self.assertEqual(self.store.get(SESSION,TURN)["state"],"cancelled")


class NativeToolHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.conversations=ConversationStore(cls.temp.name)
        cls.cards=CharacterStore(Path(cls.temp.name)/"character")
        cls.images=ImageJobStore(Path(cls.temp.name)/"images")
        cls.gateway=GatewayServer(("127.0.0.1",0),api_key="secret-for-test-only",
            upstream_key="fake-test-only",upstream_host="127.0.0.1",
            upstream_port=1,conversations=cls.conversations,characters=cls.cards,
            image_jobs=cls.images,tool_calling_enabled=True)
        cls.thread=threading.Thread(target=cls.gateway.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.gateway.shutdown()
        cls.gateway.server_close()
        cls.thread.join(2)
        cls.temp.cleanup()

    def request(self,method,path,obj=None,key="secret-for-test-only",origin=None):
        c=http.client.HTTPConnection("127.0.0.1",self.gateway.server_address[1],timeout=5)
        headers={"Authorization":"Bearer "+key} if key else {}
        if origin:headers["Origin"]=origin
        body=json.dumps(obj).encode() if obj is not None else None
        if body:headers["Content-Type"]="application/json"
        c.request(method,path,body=body,headers=headers)
        res=c.getresponse()
        raw=res.read()
        c.close()
        return res.status,json.loads(raw)

    def payload(self,turn=TURN,session=SESSION):
        return {"session_id":session,"turn_id":turn,"model":"mock-model",
                "messages":[{"role":"user","content":"Please draw a small cat"}],
                "reasoning_effort":"none"}

    def test_text_and_idempotent_replay(self):
        with patch.object(self.gateway.chat_turns,"_official",return_value=model_decision()) as model:
            status,value=self.request("POST","/v1/mikuchin/chat/turns",self.payload())
            self.assertEqual(status,200)
            self.assertEqual(value["state"],"text_done")
            self.assertEqual(value["text"],"这是普通文本回答")
            status,replay=self.request("POST","/v1/mikuchin/chat/turns",self.payload())
            self.assertEqual(status,200)
            self.assertEqual(replay["turn_id"],TURN)
            self.assertEqual(model.call_count,1)
        self.assertEqual(self.request("GET",f"/v1/mikuchin/chat/turns/{TURN}?session_id={OTHER}")[0],404)
        self.assertEqual(self.request("GET",f"/v1/mikuchin/chat/turns/{TURN}?session_id={SESSION}")[1]["state"],"text_done")

    def test_local_dispatch_once(self):
        req={"prompt":"a cat","strata_image_profile":"local-fake","size":"512x512","strata_upscale":"off"}
        meta={"profile":"local-fake","online":False,"edit_previous":False,"model_name":"mock"}
        with patch.object(self.gateway.chat_turns,"_official",return_value=model_decision("generate_image")), \
             patch.object(service_module,"resolve_image_request",return_value=(req,meta)), \
             patch.object(self.images,"worker_healthy",return_value=True), \
             patch.object(self.images,"_require_provider",return_value=None):
            status,turn=self.request("POST","/v1/mikuchin/chat/turns",self.payload(TURN2))
            self.assertEqual(status,200)
            self.assertEqual(turn["state"],"running")
            self.assertFalse(turn["online"])
            self.assertTrue(turn["job_id"])
            status,replay=self.request("POST","/v1/mikuchin/chat/turns",self.payload(TURN2))
            self.assertEqual(status,200)
            self.assertEqual(replay["job_id"],turn["job_id"])
            rows=self.images.listing(None,session_id=SESSION)["jobs"]
            self.assertEqual(len([j for j in rows if j["request_id"]==TURN2]),1)

    def test_paid_approval_and_cancel(self):
        turn="e"*32
        req={"prompt":"a cat","strata_image_profile":"api-fake","size":"512x512","strata_upscale":"off"}
        meta={"profile":"api-fake","online":True,"edit_previous":False,"model_name":"pay/mock"}
        with patch.object(self.gateway.chat_turns,"_official",return_value=model_decision("generate_image")), \
             patch.object(service_module,"resolve_image_request",return_value=(req,meta)):
            status,started=self.request("POST","/v1/mikuchin/chat/turns",self.payload(turn))
        self.assertEqual(status,200)
        self.assertEqual(started["state"],"awaiting_approval")
        self.assertTrue(started["approval_token"])
        self.assertFalse(self.images.listing(None,session_id=SESSION)["jobs"][-1].get("request_id")==turn)
        status,_=self.request("POST",f"/v1/mikuchin/chat/turns/{turn}/approve",
            {"session_id":SESSION,"approval_token":"badtoken"*7})
        self.assertEqual(status,400)
        status,end=self.request("POST",f"/v1/mikuchin/chat/turns/{turn}/cancel",
            {"session_id":SESSION})
        self.assertEqual(status,200)
        self.assertEqual(end["state"],"cancelled")

    def test_origin_and_authentication(self):
        status,_=self.request("POST","/v1/mikuchin/chat/turns",self.payload(),"invalid")
        self.assertEqual(status,401)
        status,_=self.request("POST","/v1/mikuchin/chat/turns",self.payload("f"*32),
                              origin="https://evil.invalid")
        self.assertEqual(status,403)

    def test_stop_during_model_decision_never_dispatches(self):
        ident="9"*32
        entered=threading.Event()
        release=threading.Event()
        responses=[]
        def slow_model(_payload):
            entered.set()
            if not release.wait(8):
                raise TimeoutError("test gate")
            return model_decision("generate_image")
        with patch.object(self.gateway.chat_turns,"_official",side_effect=slow_model), \
             patch.object(service_module,"resolve_image_request") as resolver:
            thread=threading.Thread(target=lambda:responses.append(
                self.request("POST","/v1/mikuchin/chat/turns",self.payload(ident))),
                daemon=True)
            thread.start()
            self.assertTrue(entered.wait(4))
            status,cancelled=self.request("POST",
                f"/v1/mikuchin/chat/turns/{ident}/cancel",{"session_id":SESSION})
            self.assertEqual(status,200)
            self.assertEqual(cancelled["state"],"cancelled")
            release.set()
            thread.join(4)
            self.assertEqual(responses[0][1]["state"],"cancelled")
            resolver.assert_not_called()
            self.assertIsNone(self.images.chat_lookup(SESSION,ident))

    def test_frozen_existing_request_link_can_be_read_directly(self):
        ident="8"*32
        with patch.object(self.images,"worker_healthy",return_value=True), \
             patch.object(self.images,"_require_provider",return_value=None):
            added=self.images.chat_submit(SESSION,ident,
                {"prompt":"test","strata_image_profile":"local-fake","size":"512x512",
                 "strata_upscale":"off"})
        existing=self.images.chat_lookup(SESSION,ident)
        self.assertIsNotNone(existing)
        self.assertEqual(existing["id"],added["id"])
        self.assertEqual(existing["request_id"],ident)
        self.assertIsNone(self.images.chat_lookup(OTHER,ident))

    def test_worker_offline_reports_failure_without_job(self):
        ident="7"*32
        req={"prompt":"a cat","strata_image_profile":"local-fake",
             "size":"512x512","strata_upscale":"off"}
        meta={"profile":"local-fake","online":False,
              "edit_previous":False,"model_name":"mock"}
        with patch.object(self.gateway.chat_turns,"_official",
                          return_value=model_decision("generate_image")), \
             patch.object(service_module,"resolve_image_request",
                          return_value=(req,meta)), \
             patch.object(self.images,"worker_healthy",return_value=False):
            status,answer=self.request("POST","/v1/mikuchin/chat/turns",
                                       self.payload(ident))
        self.assertEqual(status,200)
        self.assertEqual(answer["state"],"unavailable")
        self.assertIsNone(self.images.chat_lookup(SESSION,ident))

    def test_reject_unsupported_request_fields(self):
        req=self.payload("1"*32)
        req["strata_mcp"]=True
        status,result=self.request("POST","/v1/mikuchin/chat/turns",req)
        self.assertEqual(status,400)
        self.assertEqual(result["error"]["type"],"invalid_request")


if __name__=="__main__":unittest.main()
