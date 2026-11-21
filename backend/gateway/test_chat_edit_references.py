"""Native edit_image references and non-reference redraw fallback (offline)."""
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from backend.gateway.image_jobs import ImageJobStore
from backend.gateway.chat_turns import ChatTurnStore


class NativeEditReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.jobs=ImageJobStore(Path(self.temp.name)/"images",embedded_worker=True)
        self.jobs._require_provider=lambda request: {"id":"api-local-fixture"}
        self.jobs._start_worker=lambda:None
        self.session="a"*32
        picture=Image.new("RGB",(128,128),(28,192,192))
        data=io.BytesIO()
        picture.save(data,"PNG")
        self.png=data.getvalue()
        self.file="b"*32+".png"
        root=self.jobs.root/"generated-images"
        root.mkdir(exist_ok=True)
        (root/self.file).write_bytes(self.png)
        original=self.jobs._prepare({"prompt":"初音未来，蓝绿色双马尾，舞台上",
                           "size":"1024x1024","strata_image_profile":"fixture-api",
                           "strata_upscale":"off"})
        with self.jobs._db() as db:
            prior=self.jobs._insert(db,original,"running")
            db.execute("UPDATE jobs SET state='success',result_json=? WHERE id=?",
                       (json.dumps({"image_file":self.file}),prior["id"]))
            db.execute("""INSERT INTO chat_image_requests(session_id,request_id,job_id,created)
                         VALUES(?,?,?,0)""",(self.session,"c"*32,prior["id"]))
        self.original=prior["id"]

    def tearDown(self):
        self.temp.cleanup()

    def edit(self,mode,refs=None,request_id=None):
        user={"prompt":"把上一张初音未来改成二次元风格",
              "strata_image_profile":"fixture-api","size":"1024x1024","strata_upscale":"off"}
        if refs:user["strata_reference_assets"]=refs
        with patch("backend.gateway.image_jobs.providers.get",
                   return_value={"reference_mode":mode}):
            return self.jobs.chat_submit(self.session,request_id or "d"*32,
                                         user,edit_previous=True)

    def test_multi_api_receives_prior_and_user_reference(self):
        data="data:image/png;base64,"+base64.b64encode(self.png).decode()
        job=self.edit("multi",refs=[{"name":"用户参考图.png","data_url":data}])
        self.assertEqual(job["state"],"running")
        self.assertEqual(job["source_id"],self.original)
        self.assertEqual(len(job["request"]["strata_reference_assets"]),2)
        self.assertEqual(job["request"]["strata_reference_assets"][0]["name"],"previous-chat-image.png")
        self.assertEqual(job["request"]["strata_reference_assets"][1]["name"],"用户参考图.png")
        for ref in job["request"]["strata_reference_assets"]:
            self.jobs.reference_bytes(ref["id"])

    def test_single_api_selects_prior_without_overpromising_two_images(self):
        data="data:image/png;base64,"+base64.b64encode(self.png).decode()
        job=self.edit("single",refs=[{"data_url":data}],request_id="e"*32)
        self.assertEqual(len(job["request"]["strata_reference_assets"]),1)
        self.assertEqual(job["source_id"],self.original)

    def test_no_reference_api_falls_back_to_previous_prompt_plus_new_instruction(self):
        job=self.edit("none",request_id="f"*32)
        self.assertEqual(job["source_id"],self.original)
        self.assertEqual(job["request"]["strata_reference_assets"],[])
        self.assertIn("初音未来，蓝绿色双马尾",job["request"]["prompt"])
        self.assertIn("二次元风格",job["request"]["prompt"])

    def test_unauthorized_studio_still_cannot_set_chat_runtime_flag(self):
        with self.assertRaisesRegex(ValueError,"invalid image request fields"):
            self.jobs._prepare({"prompt":"x","strata_chat_runtime_mode":"concurrent"})


class BackgroundTurnTests(unittest.TestCase):
    def test_background_mode_is_frozen_in_the_turn_db(self):
        with tempfile.TemporaryDirectory() as root:
            db=ChatTurnStore(root)
            sid,tid="a"*32,"b"*32
            req={"messages":[{"role":"user","content":"画初音未来"}],"model":"mock"}
            db.create(sid,tid,req)
            tool={"name":"generate_image","tool_call_id":"call_miku","arguments":{"prompt":"Miku"}}
            db.decision_tool(sid,tid,tool,
                {"prompt":"Miku","_chat_runtime_mode":"concurrent"},
                {"online":False,"profile":"local-qwen-official"})
            self.assertTrue(db.public(sid,tid)["background"])
            tid2="c"*32
            db.create(sid,tid2,req)
            db.decision_tool(sid,tid2,tool,
                {"prompt":"Miku","_chat_runtime_mode":"exclusive"},
                {"online":False,"profile":"local-qwen-official"})
            self.assertFalse(db.public(sid,tid2)["background"])


if __name__=="__main__":unittest.main()
