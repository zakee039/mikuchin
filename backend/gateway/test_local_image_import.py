"""Safe local Qwen-Image / SDXL model registration; no GPU or network providers."""
from __future__ import annotations
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from backend.gateway.app import GatewayServer
from backend.gateway.image_jobs import ImageJobStore
from backend.gateway import local_images
from backend.gateway.chat_turns import ChatTurnStore
from unittest.mock import patch


class LocalImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.jobs=ImageJobStore(self.root/"images")
        files={}
        for key,ext in (("exe",".exe"),("diffusion_model",".gguf"),
                        ("vae",".safetensors"),("llm",".gguf")):
            p=self.root/(key+ext)
            p.write_bytes(b"local-test-model-file")
            files[key]=str(p)
        self.files=files
        path=local_images.config_path(self.jobs)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"profiles":[{
            "id":"local-base","name":"Trusted sd-cli","family":"qwen_turbo",
            "max_side":1024,"args":["--flash-attn","off"],
            **files
        }],"loras":[{"id":"test","path":"somewhere.safetensors"}],
          "upscaler":{"enabled":False}}),encoding="utf-8")
        self.base_config=json.loads(path.read_text(encoding="utf-8"))
        self.gateway=GatewayServer(("127.0.0.1",0),
            api_key="local-test-key",upstream_key="test-upstream-key",
            upstream_host="127.0.0.1",upstream_port=1,image_jobs=self.jobs)
        self.thread=threading.Thread(target=self.gateway.serve_forever,daemon=True)
        self.thread.start()
        self.model={"name":"导入 Qwen 测试","base_id":"local-base",
            "diffusion_model":files["diffusion_model"],
            "vae":files["vae"],"llm":files["llm"],"llm_vision":""}

    def tearDown(self):
        self.gateway.shutdown();self.gateway.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self,body,*,host=None,origin=None,forwarded=None,key=True):
        c=http.client.HTTPConnection("127.0.0.1",self.gateway.server_address[1],timeout=7)
        port=self.gateway.server_address[1]
        host=host or "127.0.0.1:"+str(port)
        headers={"Host":host,"Content-Type":"application/json"}
        if key:headers["Authorization"]="Bearer local-test-key"
        if origin is not None:headers["Origin"]=origin
        if forwarded:headers["CF-Connecting-IP"]="203.0.113.3"
        c.request("POST","/v1/mikuchin/local-image-models",
                  body=json.dumps(body).encode("utf-8"),headers=headers)
        result=c.getresponse()
        status=result.status
        content=json.loads(result.read())
        c.close()
        return status,content

    def origin(self):
        return "http://127.0.0.1:"+str(self.gateway.server_address[1])

    def test_import_keeps_existing_profiles_loras_and_engine_exec(self):
        status,body=self.request({"action":"import","model":self.model},origin=self.origin())
        self.assertEqual(status,200,body)
        config=local_images._settings(self.jobs)
        self.assertEqual(len(config["profiles"]),2)
        self.assertEqual(config["loras"],self.base_config["loras"])
        self.assertEqual(config["upscaler"],self.base_config["upscaler"])
        old,new=config["profiles"]
        self.assertEqual(old,self.base_config["profiles"][0])
        self.assertTrue(new["id"].startswith("local-import-"))
        self.assertEqual(new["exe"],old["exe"])
        self.assertEqual(new["args"],old["args"])
        self.assertTrue(local_images._profile_good(new))
        self.assertEqual(local_images.get(self.jobs,new["id"])["model"],"导入 Qwen 测试")

    def test_no_browser_executable_injection(self):
        bad={**self.model,"exe":"C:\\Windows\\System32\\cmd.exe"}
        status,response=self.request({"action":"import","model":bad},origin=self.origin())
        self.assertEqual(status,400)
        self.assertIn("未知字段",response["error"]["message"])
        self.assertEqual(len(local_images._settings(self.jobs)["profiles"]),1)

    def test_reject_missing_model_files_and_wrong_extension(self):
        for bad in (str(self.root/"missing.gguf"),self.files["exe"]):
            with self.subTest(bad=bad):
                model={**self.model,"diffusion_model":bad}
                status,_=self.request({"action":"import","model":model},origin=self.origin())
                self.assertEqual(status,400)
        self.assertEqual(len(local_images._settings(self.jobs)["profiles"]),1)

    def test_sdxl_single_checkpoint_import_preserves_qwen_and_loras(self):
        checkpoint=self.root/"sdxl-base.safetensors"
        checkpoint.write_bytes(b"mock SDXL checkpoint; no GPU work")
        model={"name":"SDXL Base 1.0","family":"sdxl","base_id":"local-base",
               "checkpoint":str(checkpoint)}
        status,result=self.request({"action":"import","model":model},origin=self.origin())
        self.assertEqual(status,200,result)
        data=local_images._settings(self.jobs)
        self.assertEqual(len(data["profiles"]),2)
        self.assertEqual(data["profiles"][0],self.base_config["profiles"][0])
        self.assertEqual(data["loras"],self.base_config["loras"])
        self.assertEqual(data["upscaler"],self.base_config["upscaler"])
        profile=data["profiles"][1]
        self.assertEqual(profile["checkpoint"],str(checkpoint))
        self.assertEqual(profile["family"],"sdxl")
        self.assertEqual(profile["steps"],28)
        self.assertEqual(profile["cfg_scale"],7.0)
        self.assertEqual(profile["args"],[])
        self.assertNotIn("diffusion_model",profile)

    def test_sdxl_import_rejects_executable_override(self):
        checkpoint=self.root/"sdxl.safetensors"
        checkpoint.write_bytes(b"fake checkpoint")
        model={"name":"SDXL","family":"sdxl","base_id":"local-base",
               "checkpoint":str(checkpoint),"exe":self.files["exe"]}
        status,_=self.request({"action":"import","model":model},origin=self.origin())
        self.assertEqual(status,400)
        self.assertEqual(len(local_images._settings(self.jobs)["profiles"]),1)

    def test_only_same_origin_localhost_browser_with_auth(self):
        payload={"action":"import","model":self.model}
        bad=[
            {"origin":None},
            {"origin":"http://example.com"},
            {"host":"key.zakee.fun","origin":"http://key.zakee.fun"},
            {"origin":self.origin(),"forwarded":True},
            {"origin":self.origin(),"key":False},
        ]
        for case in bad:
            with self.subTest(case=case):
                status,_=self.request(payload,**case)
                self.assertIn(status,(401,403))
        self.assertEqual(len(local_images._settings(self.jobs)["profiles"]),1)


class TurnTimingSummaryTests(unittest.TestCase):
    def test_queue_timestamp_not_exposed_as_started_time(self):
        with tempfile.TemporaryDirectory() as root:
            turns=ChatTurnStore(root)
            session,ident="a"*32,"b"*32
            turns.create(session,ident,{"model":"test","messages":[{"role":"user","content":"miku"}]})
            turns.decision_tool(session,ident,{"name":"generate_image",
                "tool_call_id":"call_miku","arguments":{"prompt":"miku"}},
                {"prompt":"miku"},{"online":False,"profile":"local-qwen"})
            with patch.object(turns,"job_for",return_value={
                "id":"c"*32,"state":"running","phase":"排队等待执行",
                "started_at":None,"finished_at":None,"elapsed_s":None,"result":{}}):
                result=turns.public(session,ident,jobs=object())
                self.assertIsNone(result["job"]["started_at"])
                self.assertIsNone(result["job"]["elapsed_s"])
            with patch.object(turns,"job_for",return_value={
                "id":"c"*32,"state":"success","phase":"已完成",
                "started_at":1000.0,"finished_at":1075.0,
                "elapsed_s":75.0,"result":{"image_file":"d"*32+".png"}}):
                result=turns.public(session,ident,jobs=object())
                self.assertEqual(result["job"]["started_at"],1000)
                self.assertEqual(result["job"]["elapsed_s"],75)


if __name__=="__main__":unittest.main()
