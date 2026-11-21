"""Disposable browser E2E fixture for Native Gateway P0 chat compatibility.

No real GPU, paid image calls, production ports, user data, or credentials.
Start with: python -u -B scripts/smoke-native-chat-browser.py
Prints a JSON port, then runs until the printed stop-file is created.
"""
from __future__ import annotations

import json
import io
import secrets
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.gateway import app as gateway_app
from backend.gateway.app import GatewayServer
from backend.gateway.characters import CharacterStore
from backend.gateway.conversations import ConversationStore
from backend.gateway.image_jobs import ImageJobStore
from backend.gateway import image_providers

TEST_KEY = "native-p0-browser-test-key"
OFFICIAL_KEY = "native-p0-browser-upstream-test-key"


class FakeChatEngine(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    recorded = None
    tools_mode = False
    vision_images = 0
    decisions = []
    context_audits = []
    worker_offline = False
    fail_vision_once = False

    def log_message(self, *_args):
        pass

    def send_json(self, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_sse(self, chunks, *, pause_after_first=0):
        self.send_response(200)
        self.send_header("Content-Type","text/event-stream; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Connection","close")
        self.end_headers()
        self.close_connection=True
        for i,delta in enumerate(chunks):
            obj={"choices":[{"index":0,"delta":delta,
                             "finish_reason":delta.pop("_finish",None)}]}
            self.wfile.write(("data: "+json.dumps(obj,ensure_ascii=False)+"\n\n").encode())
            self.wfile.flush()
            if i==0 and pause_after_first:time.sleep(pause_after_first)
            else:time.sleep(0.12)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + OFFICIAL_KEY:
            self.send_error(401)
            return
        if self.path == "/health":
            self.send_json({"status": "ok", "model": "browser-e2e-mock",
                            "loaded": True, "images": True})
        elif self.path == "/api/models":
            self.send_json({"models": [{"id": "browser-e2e-mock", "current": True}]})
        elif self.path == "/v1/models":
            self.send_json({"data": [{"id": "browser-e2e-mock"}]})
        elif self.path == "/metrics":
            self.send_json({"live":{"state":"idle"},"totals":{},"hardware":{}})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + OFFICIAL_KEY:
            self.send_error(401)
            return
        count = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(count))
        record = {"fields":sorted(body), "messages":body.get("messages", []) if not self.tools_mode else
                  [m.get("role") for m in body.get("messages", [])],
                  "image_tool":body.get("strata_image_tool", "absent"),
                  "budget":body.get("answer_budget_tokens", "absent")}
        with self.recorded.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        chat=body.get("messages") or []
        if self.tools_mode and body.get("tool_choice")=="none":
            if FakeChatEngine.fail_vision_once:
                FakeChatEngine.fail_vision_once=False
                self.send_error(503,"Deliberate mock vision failure")
                return
            final=chat[-1].get("content") if chat else None
            picture=bool(isinstance(final,list) and any(
                p.get("type")=="image_url" and
                p.get("image_url",{}).get("url","").startswith("data:image/jpeg;base64,")
                for p in final if isinstance(p,dict)))
            linked=any(m.get("role")=="tool" and m.get("tool_call_id")=="call_native_browser"
                       for m in chat)
            if picture and linked:
                FakeChatEngine.vision_images+=1
            self.send_json({"choices":[{"finish_reason":"stop","message":{
                "role":"assistant","content":"刚刚画好了这张图片，接下来可以调整背景或眼睛。"}}]})
            return
        if self.tools_mode and body.get("tools"):
            latest=next((m for m in reversed(chat) if m.get("role")=="user"),{})
            c=latest.get("content","")
            user_text=c if isinstance(c,str) else " ".join(p.get("text","")
                for p in c if isinstance(p,dict) and p.get("type")=="text")
            if "再生成一张二次元的" in user_text:
                past=chat[:-1]
                earlier_miku=any(
                    "初音未来" in str(m.get("content","")) or
                    "Hatsune Miku" in str(m.get("tool_calls",[]))
                    for m in past)
                FakeChatEngine.context_audits.append({
                    "has_prior_miku_subject":earlier_miku,
                    "roles":[m.get("role") for m in chat],
                    "has_prior_tool_call":any(m.get("tool_calls") for m in past),
                })
            if "测试模型决策取消" in user_text and not body.get("stream"):
                time.sleep(4)
            if "测试Worker失联" in user_text:
                FakeChatEngine.worker_offline=True
            if "恢复Worker" in user_text:
                FakeChatEngine.worker_offline=False
            if "测试视觉尾部失败" in user_text:
                FakeChatEngine.fail_vision_once=True
            if "测试非法工具" in user_text:
                self.send_json({"choices":[{"finish_reason":"tool_calls","message":{
                    "role":"assistant","content":None,"tool_calls":[{"id":"call_native_browser",
                        "type":"function","function":{"name":"shell",
                            "arguments":"{\"command\":\"no\"}"}}]}}]})
                return
            edit=any(x in user_text for x in ("眼睛调大","背景改","修改这张","编辑上一张"))
            if not edit and any(x in user_text for x in ("不要生成","不要画",
                                                         "解释","如何","如果","成绩表","Excel","建议")):
                FakeChatEngine.decisions.append("text")
                if body.get("stream"):
                    content="P0_BROWSER_OK：这次只回答文字，没有调用图片工具。"
                    self.send_sse([{"reasoning_content":"先阅读请求，"},{"reasoning_content":"不需要调用生图工具。"},
                                   {"content":content[:14]},{"content":content[14:]},
                                   {"_finish":"stop"}],
                        pause_after_first=3.5 if "测试模型决策取消" in user_text else 0)
                    return
                self.send_json({"choices":[{"finish_reason":"stop","message":{
                    "role":"assistant","content":"P0_BROWSER_OK：这次只回答文字，没有调用图片工具。"}}]})
                return
            name="edit_image" if edit else "generate_image"
            FakeChatEngine.decisions.append(name)
            arguments={"instruction":user_text} if edit else {"prompt":user_text}
            if body.get("stream"):
                args=json.dumps(arguments,ensure_ascii=False)
                self.send_sse([
                    {"reasoning_content":"读取用户请求，决定使用图片工具。"},
                    {"tool_calls":[{"index":0,"id":"call_native_browser",
                        "type":"function","function":{"name":name,"arguments":args[:8]}}]},
                    {"tool_calls":[{"index":0,"function":{"arguments":args[8:]}}]},
                    {"_finish":"tool_calls"}],
                    pause_after_first=3.5 if "测试模型决策取消" in user_text else 0)
                return
            self.send_json({"choices":[{"finish_reason":"tool_calls","message":{
                "role":"assistant","content":None,"tool_calls":[{"id":"call_native_browser",
                    "type":"function","function":{"name":name,
                        "arguments":json.dumps(arguments,ensure_ascii=False)}}]}}]})
            return
        if chat and chat[0].get("role")=="system" and "MIKUCHIN_IMAGE_ROUTER_V1" in chat[0].get("content",""):
            text=json.loads(chat[-1]["content"]).get("user_text","").lower()
            action=("edit" if any(term in text for term in ("编辑","修改","change","edit","眼睛"))
                    else "generate" if any(term in text for term in ("画","生成图片","draw","create an image"))
                    else "text")
            self.send_json({"choices":[{"message":{"role":"assistant",
                "content":json.dumps({"action":action})},"finish_reason":"stop"}]})
            return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            for data in [
                {"choices":[{"delta":{"content":"P0_BROWSER_OK"},"finish_reason":None}]},
                {"choices":[{"delta":{},"finish_reason":"stop"}],
                 "usage":{"prompt_tokens":14,"completion_tokens":3}},
            ]:
                self.wfile.write(b"data: " + json.dumps(data).encode() + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_json({"choices":[{"message":{"role":"assistant","content":"P0_BROWSER_OK"},
                                        "finish_reason":"stop"}]})


def main():
    FakeChatEngine.tools_mode = "--tools" in sys.argv
    paid_consent_fixture = "--paid" in sys.argv
    confirm_fixture = "--confirm" in sys.argv
    # All state is disposable. Fixture is explicitly stopped by creating the
    # reported control file so Windows processes and ports can be verified free.
    with tempfile.TemporaryDirectory(prefix="mikuchin-p0-browser-") as root:
        directory = Path(root)
        stop_file = directory / "STOP"
        recorded = directory / "forwarded.jsonl"
        FakeChatEngine.recorded = recorded
        official = ThreadingHTTPServer(("127.0.0.1", 0), FakeChatEngine)
        # Preserve the same capability mismatch as a real local Qwen model:
        # Image Studio is available, but the in-chat tool is NOT.
        original_catalog = gateway_app.local_images.catalog
        gateway_app.local_images.catalog = lambda _jobs: ([{"id":"local-mock","available":True}], [])
        jobs=ImageJobStore(directory / "images",embedded_worker=True)
        # The disposable embedded worker can execute immediately; unlike the
        # production independent worker it never sends heartbeats. Report
        # ready only in this isolated browser fixture.
        jobs.worker_healthy = lambda: not FakeChatEngine.worker_offline
        original_provider_catalog = image_providers.catalog
        # Pretend this TEST-ONLY fake PNG provider is locally hosted so a
        # native JS billing confirmation cannot block headless automation.
        # The provider below writes a local 64x64 PNG and never uses HTTP.
        if not paid_consent_fixture:
            image_providers.catalog = lambda store: [
                {**item, "family": "qwen_turbo"}
                for item in original_provider_catalog(store)]
        fake_service=image_providers.save_service(jobs,{
            "name":"Disposable fixture (no paid calls)",
            "base_url":"http://127.0.0.1:19999/v1",
            "model":"browser-fake-png",
            "api_key":"NO_NETWORK_TEST_KEY","sizes":"standard",
            "chat_confirm_each_call":confirm_fixture,
            "reference_mode":"multi"})
        cards=CharacterStore(directory / "character")
        cards.set_global({"default_role":"ordinary",
            "chat_image_profile":fake_service["id"],
            "chat_image_settings":{"lora_id":"none","width":1024,"height":1024,
                                   "upscale":"off","steps":None}},
            allowed_image_profiles={fake_service["id"]},
            image_profile_configs={fake_service["id"]:{"family":"api" if paid_consent_fixture else "qwen_turbo","max_side":2048,
                                   "sizes":"standard","upscale_available":False}})
        fake_calls=[]
        def fake_image_provider(store, request, *, on_status, diagnostic_id, **kwargs):
            fake_calls.append({"job_id":diagnostic_id,
                               "reference_count":len(request.get("strata_reference_images",[]))})
            on_status("Mock: local PNG only; no network or payment")
            if "测试慢任务" in str(request.get("prompt","")):
                time.sleep(5)
            folder=directory/"images"/"generated-images"
            folder.mkdir(exist_ok=True)
            name=secrets.token_hex(16)+".png"
            image=Image.new("RGB",(64,64),(46,185,172))
            image.save(folder/name)
            return {"model":"mock-png","size":request["size"],
                    "strata":{"image_file":name,"seconds":.01}}
        jobs._provider=fake_image_provider
        gateway = GatewayServer(("127.0.0.1", 0), api_key=TEST_KEY, upstream_key=OFFICIAL_KEY,
                                upstream_host="127.0.0.1", upstream_port=official.server_address[1],
                                conversations=ConversationStore(directory),
                                characters=cards,image_jobs=jobs,
                                tool_calling_enabled=FakeChatEngine.tools_mode)
        threads = [threading.Thread(target=x.serve_forever,daemon=True)
                   for x in (official,gateway)]
        for thread in threads:
            thread.start()
        print(json.dumps({"gateway_port":gateway.server_address[1],
                          "stop_file":str(stop_file), "forwarded_file":str(recorded),
                          "key":TEST_KEY, "tool_calling":FakeChatEngine.tools_mode,
                          "paid_consent_fixture":paid_consent_fixture}),flush=True)
        try:
            while not stop_file.exists():
                time.sleep(.2)
        finally:
            gateway_app.local_images.catalog = original_catalog
            image_providers.catalog = original_provider_catalog
            for server in (gateway, official):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=3)
            # Report only synthetic-test flags, never user credentials.
            if recorded.exists():
                lines = recorded.read_text(encoding="utf-8").splitlines()
                print("forwarded_requests=" + str(len(lines)), flush=True)
            jobs.queue.join()
            print("fake_image_provider_calls="+str(len(fake_calls)),flush=True)
            print("fake_image_reference_counts="+",".join(str(c["reference_count"])
                for c in fake_calls),flush=True)
            print("fake_model_decisions="+",".join(FakeChatEngine.decisions),flush=True)
            print("fake_vision_images="+str(FakeChatEngine.vision_images),flush=True)
            print("context_audit="+json.dumps(FakeChatEngine.context_audits,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
