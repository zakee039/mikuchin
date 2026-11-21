"""Native image follow-up lifecycle: real context, idempotent and no billable retry."""
from __future__ import annotations
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.gateway.chat_turn_service import TurnCoordinator
from backend.gateway.chat_turns import ChatTurnStore
from backend.gateway.image_tool_feedback import classify_error,redact_error

SESSION="a"*32
TURN="b"*32

class FakeJobs:
    def __init__(self,root):
        self.root=Path(root)/"images"
        self.root.mkdir(exist_ok=True)
        self.job={"id":"img-"+"c"*24,"state":"running","phase":"调用图像 API",
                  "result":{},"error":""}
        self.submissions=0
    def chat_lookup(self,session,turn):
        if session!=SESSION or turn!=TURN: return None
        return self.job

class ImageEventFollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ChatTurnStore(self.tmp.name)
        self.jobs=FakeJobs(self.tmp.name)
        self.c=object.__new__(TurnCoordinator)
        self.c.store=self.store
        self.c._lock=threading.Lock()
        self.c._conversation_decisions={}
        self.c.server=SimpleNamespace(image_jobs=self.jobs,
            conversations=SimpleNamespace(get=lambda sid:{
                "web_messages":[
                    {"role":"user","text":"把上一张初音未来的衣服调成淡蓝色"},
                    {"role":"assistant","text":"之前那张图片我看过"},
                    {"role":"user","text":"背景也用柔和的蓝色"}
                ] if sid==SESSION else []}))
        self.request={"model":"local-test-llm","messages":[
            {"role":"system","content":"你是温和的助手。"},
            {"role":"user","content":"把上一张初音未来的衣服调成淡蓝色"}]}
        self.store.create(SESSION,TURN,self.request)
        self.store.decision_tool(SESSION,TURN,{
            "name":"edit_image","tool_call_id":"call_miku",
            "arguments":{"instruction":"把初音未来衣服改成淡蓝色"}},
            {"prompt":"初音未来的淡蓝色衣服","strata_image_profile":"api-mock"},
            {"profile":"api-mock","online":True,"require_approval":False})
        self.store.transition(SESSION,TURN,"queued","running",job_id=self.jobs.job["id"])

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self,predicate,seconds=3):
        end=time.time()+seconds
        while time.time()<end:
            row=self.store.get(SESSION,TURN)
            if predicate(row):return row
            time.sleep(0.02)
        self.fail("background followup did not finish")

    def test_started_from_conversation_not_fixed_template_and_once(self):
        calls=[]
        def answer(payload,timeout=240):
            calls.append(payload)
            return {"choices":[{"finish_reason":"stop","message":{
                "content":"好，我按刚才的初音未来画面把衣服调整为淡蓝色，完成后再告诉你。"}}]}
        with patch.object(self.c,"_official",side_effect=answer):
            self.c._start_announcement(SESSION,TURN)
            self.c._start_announcement(SESSION,TURN)
            row=self.wait(lambda r:r["start_state"]=="done")
        self.assertEqual(len(calls),1)
        self.assertIn("淡蓝色",row["start_text"])
        self.assertEqual(calls[0]["tool_choice"],"none")
        self.assertEqual(calls[0]["reasoning_effort"],"none")
        self.assertEqual(calls[0]["reasoning_budget_tokens"],0)
        self.assertIn("背景也用柔和的蓝色",str(calls[0]["messages"]))
        self.assertTrue(any(m.get("role")=="tool" for m in calls[0]["messages"]))
        self.assertEqual(self.store.public(SESSION,TURN,self.jobs)["start_text"],row["start_text"])

    def test_provider_moderation_failure_has_actual_evidence(self):
        calls=[]
        def answer(payload,timeout=240):
            calls.append(payload)
            return {"choices":[{"finish_reason":"stop","message":{"content":
                "API 报错了，服务明确返回 content_policy_violation（审核拦截）。"
                "可以调整为普通服饰设计的描述；需要我重新提交吗？"}}]}
        with patch.object(self.c,"_official",side_effect=answer):
            self.jobs.job.update({"state":"failed","phase":"任务失败",
                "error":"ImageProviderError: image API HTTP 400: content_policy_violation (nudity)"})
            self.c.reconcile(SESSION,TURN)
            done=self.wait(lambda r:r["state"]=="image_failed")
            self.c.reconcile(SESSION,TURN)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.jobs.submissions,0)
        self.assertIn("content_policy_violation",done["error"])
        self.assertIn("审核拦截",done["text"])
        self.assertIn("moderation_block",str(calls[0]["messages"]))
        self.assertIn("背景也用柔和的蓝色",str(calls[0]["messages"]))
        self.assertEqual(calls[0]["tool_choice"],"none")
        self.assertEqual(calls[0]["reasoning_effort"],"none")
        self.assertEqual(self.store.public(SESSION,TURN,self.jobs)["state"],"image_failed")

    def test_timeout_unknown_must_not_guess_nudity(self):
        self.assertEqual(classify_error("image API HTTP 400: Bad Request")[0],
                         "unknown_provider_error")
        self.assertEqual(classify_error("HTTPSConnectionPool: Read timed out")[0],"timeout")
        self.assertEqual(classify_error("image API HTTP 429: quota exceeded")[0],"quota_error")
        self.assertEqual(classify_error("image API HTTP 401: invalid API key")[0],"auth_error")
        self.assertNotIn("sk-secretsecret123",redact_error(
            "image API HTTP 400: sk-secretsecret123 https://example.com/api?token=123"))
        self.assertIn("[private endpoint]",redact_error("https://example.com/api?token=123"))

    def test_failure_model_outage_has_one_natural_fallback(self):
        self.jobs.job.update({"state":"failed","error":"Connection reset by peer"})
        with patch.object(self.c,"_official",side_effect=TimeoutError("unreachable")) as model:
            self.c.reconcile(SESSION,TURN)
            done=self.wait(lambda r:r["state"]=="image_failed")
            self.c.reconcile(SESSION,TURN)
        self.assertEqual(model.call_count,1)
        self.assertIn("没有自动",done["text"])
        self.assertEqual(self.jobs.submissions,0)

    def test_restart_does_not_retry_uncertain_followup(self):
        self.store.begin_start_reply(SESSION,TURN)
        self.store.transition(SESSION,TURN,"running","failure_running",
                              error="图像 API 已经失败")
        restored=ChatTurnStore(self.tmp.name)
        row=restored.get(SESSION,TURN)
        self.assertEqual(row["start_state"],"failed")
        self.assertEqual(row["state"],"image_failed")
        self.assertIn("重启前中断",row["text"])
        self.assertFalse(restored.begin_start_reply(SESSION,TURN))

if __name__=="__main__": unittest.main()
