"""Per-image-service, chat-only confirmation policy (zero external requests)."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .image_jobs import ImageJobStore
    from . import image_providers
    from .chat_tool_dispatch import resolve_image_request
    from .chat_turns import ChatTurnStore
except ImportError:
    from image_jobs import ImageJobStore
    import image_providers
    from chat_tool_dispatch import resolve_image_request
    from chat_turns import ChatTurnStore


class FakeCards:
    def __init__(self,profile_id):self.profile_id=profile_id
    def snapshot(self):
        return {"global":{"chat_image_profile":self.profile_id,
                          "chat_image_settings":{"width":1024,"height":1024,"upscale":"off"}}}


class ChatConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.jobs=ImageJobStore(Path(self.tmp.name)/"images")
        self.service={"name":"Fake Online Image","base_url":"https://example.invalid/v1",
                      "api_key":"testing-not-a-real-key","model":"mock-image-1",
                      "reference_mode":"single","sizes":"standard"}
        self.turn=ChatTurnStore(Path(self.tmp.name)/"turns")
        self.decision={"name":"generate_image","tool_call_id":"call_image",
                       "arguments":{"prompt":"初音未来插画"}}

    def tearDown(self):self.tmp.cleanup()

    def _profile(self,service):
        return resolve_image_request(FakeCards(service["id"]),self.jobs,self.decision)

    def test_default_unchecked_persists_and_queues_without_confirmation(self):
        service=image_providers.save_service(self.jobs,self.service)
        self.assertIs(service["chat_confirm_each_call"],False)
        self.assertIs(image_providers.list_services(self.jobs)[0]["chat_confirm_each_call"],False)
        request,profile=self._profile(service)
        self.assertTrue(profile["online"])
        self.assertFalse(profile["require_approval"])
        sid="a"*32;tid="b"*32
        self.turn.create(sid,tid,{"model":"mock","messages":[{"role":"user","content":"draw"}]})
        token=self.turn.decision_tool(sid,tid,self.decision,request,profile)
        self.assertIsNone(token)
        self.assertEqual(self.turn.get(sid,tid)["state"],"queued")
        self.assertEqual(self.turn.get(sid,tid)["approval_hash"],"")

    def test_opt_in_asks_chat_and_persists_after_reopening(self):
        enabled=image_providers.save_service(self.jobs,{**self.service,"chat_confirm_each_call":True})
        _,profile=self._profile(enabled)
        self.assertTrue(profile["require_approval"])
        tid="c"*32;sid="a"*32
        self.turn.create(sid,tid,{"model":"mock","messages":[{"role":"user","content":"draw"}]})
        token=self.turn.decision_tool(sid,tid,self.decision,{"prompt":"初音未来插画"},profile)
        self.assertGreater(len(token),30)
        self.assertEqual(self.turn.get(sid,tid)["state"],"awaiting_approval")
        self.assertIs(image_providers.get(self.jobs,enabled["id"])["chat_confirm_each_call"],True)
        edited=image_providers.save_service(self.jobs,{**self.service,"id":enabled["id"],"api_key":""})
        self.assertTrue(edited["chat_confirm_each_call"])  # editing other settings preserves toggle

    def test_disabling_opt_in_does_not_require_approval(self):
        enabled=image_providers.save_service(self.jobs,{**self.service,"chat_confirm_each_call":True})
        updated=image_providers.save_service(self.jobs,{**self.service,"id":enabled["id"],
                                                    "chat_confirm_each_call":False})
        self.assertFalse(self._profile(updated)[1]["require_approval"])

    def test_policy_must_be_boolean(self):
        with self.assertRaises(image_providers.ImageServiceError):
            image_providers.save_service(self.jobs,{**self.service,
                                                   "chat_confirm_each_call":"false"})

    def test_flag_never_mutates_standalone_job_contract(self):
        service=image_providers.save_service(self.jobs,{**self.service,"chat_confirm_each_call":True})
        req={"prompt":"standalone studio request","strata_image_profile":service["id"],
             "size":"1024x1024"}
        with patch.object(self.jobs,"worker_healthy",return_value=True), \
             patch.object(self.jobs,"_require_provider",return_value=None):
            # The Studio still submits directly; consent policy isn't consulted.
            result=self.jobs.submit({"request":req})
        self.assertEqual(result["state"],"running")
        self.assertNotIn("approval_token",result)


if __name__=="__main__":unittest.main()
