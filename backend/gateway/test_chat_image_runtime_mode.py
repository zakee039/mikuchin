"""Global chat image runtime mode, no mutation to official model JSON.

The protected chat-only field is inserted after public Image Studio schema
validation. Concurrent execution holds only a shared GPU turn and never calls
LLM unload/KV snapshot endpoints. Exclusive retains the original handoff.
"""
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.gateway.characters import CharacterStore
from backend.gateway.image_jobs import ImageJobStore
from backend.gateway import local_images


class RuntimeModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.jobs=ImageJobStore(self.root/"images",embedded_worker=True)
        self.session="a"*32

    def tearDown(self):
        self.tmp.cleanup()

    def test_chat_execution_mode_is_not_a_public_studio_request_field(self):
        req={"prompt":"miku","strata_image_profile":"local-qwen-official","size":"512x512",
             "strata_upscale":"off"}
        with patch.object(self.jobs,"_require_provider",return_value={"id":"local-qwen-official"}),\
             patch.object(self.jobs,"_start_worker",return_value=None):
            concurrent=self.jobs.chat_submit(self.session,"b"*32,req,
                                             runtime_mode="concurrent")
            self.assertEqual(concurrent["request"]["strata_chat_runtime_mode"],"concurrent")
            exclusive=self.jobs.chat_submit(self.session,"c"*32,req)
            self.assertEqual(exclusive["request"]["strata_chat_runtime_mode"],"exclusive")
            with self.assertRaisesRegex(ValueError,"invalid image request fields"):
                self.jobs.submit({"request":{**req,"strata_chat_runtime_mode":"concurrent"}})
            with self.assertRaises(ValueError):
                self.jobs.chat_submit(self.session,"d"*32,req,runtime_mode="auto")

    def test_exclusive_calls_original_handoff(self):
        record=[]
        @contextlib.contextmanager
        def handoff(*args,**kwargs):
            record.append("handoff")
            yield
        with patch.object(local_images,"gpu_handoff",handoff),\
             patch.object(local_images,"gpu_turn",side_effect=AssertionError("not shared")):
            with local_images.chat_image_execution(self.jobs,{"strata_chat_runtime_mode":"exclusive"}):
                record.append("inside")
        self.assertEqual(record,["handoff","inside"])

    def test_concurrent_holds_shared_lock_and_never_unloads(self):
        record=[]
        @contextlib.contextmanager
        def shared(root,*,exclusive=False,timeout=0):
            record.append(("gpu_turn",exclusive))
            yield
        with patch.object(local_images,"gpu_handoff",side_effect=AssertionError("must not unload")),\
             patch.object(local_images,"gpu_turn",shared),\
             patch.object(local_images,"publish_state",side_effect=AssertionError("no exclusive state")):
            with local_images.chat_image_execution(self.jobs,{"strata_chat_runtime_mode":"concurrent"},
                                                    on_status=record.append):
                record.append("inside")
        self.assertEqual(record[0],("gpu_turn",False))
        self.assertIn("inside",record)
        self.assertTrue(any(isinstance(x,str) and "concurrently" in x for x in record))

    def test_invalid_or_legacy_global_settings_default_fail_closed(self):
        store=CharacterStore(self.root/"characters")
        self.assertEqual(store.default_chat_image_settings()["runtime_mode"],"exclusive")
        legacy={"lora_id":"none","height":512,"width":512,"steps":8,"upscale":"off"}
        saved=store.set_global({"chat_image_settings":legacy})
        self.assertEqual(saved["chat_image_settings"]["runtime_mode"],"exclusive")
        for mode in ("invalid",None,42,True):
            with self.assertRaises(ValueError):
                store.set_global({"chat_image_settings":{**legacy,"runtime_mode":mode}})


if __name__=="__main__":unittest.main()
