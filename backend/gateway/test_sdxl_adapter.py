"""Native SDXL / Animagine adapter tests without loading large weights or a GPU.

Compare argument semantics with old-mixed serve/images.py, never modify upstream
PolyStrata or launch paid/image inference as part of these unit tests.
"""
from __future__ import annotations
import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

from backend.gateway.image_jobs import ImageJobStore
from backend.gateway.chat_turns import ChatTurnStore
from backend.gateway.chat_turn_service import TurnCoordinator
from backend.gateway import local_images


class SdxlAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.jobs=ImageJobStore(self.root/"images")
        self.exe=self.root/"sd-cli.exe"
        self.exe.write_bytes(b"fake exe - never launched")
        self.sdxl=self.root/"animagine-xl-4.safetensors"
        self.sdxl.write_bytes(b"safe dummy checkpoint")
        self.base=self.root/"diffusion.gguf"
        self.base.write_bytes(b"dummy model")
        self.vae=self.root/"vae.safetensors"
        self.vae.write_bytes(b"dummy model")
        self.encoder=self.root/"llm.gguf"
        self.encoder.write_bytes(b"dummy model")
        self.store=local_images.config_path(self.jobs)
        self.store.parent.mkdir(parents=True,exist_ok=True)
        self.store.write_text(json.dumps({"profiles":[{
            "id":"local-qwen-base","name":"Qwen baseline","family":"qwen_turbo",
            "exe":str(self.exe),"diffusion_model":str(self.base),
            "vae":str(self.vae),"llm":str(self.encoder),
            "max_side":1024,"args":["--flash-attn","off,diffusion=on",
                                     "--backend","vulkan1","--offload-to-cpu","--vae-tiling"]
        }],"loras":[],"upscaler":{}}),encoding="utf-8")
        self.settings={"name":"Animagine XL 4.0 Opt","base_id":"local-qwen-base",
                       "family":"sdxl","checkpoint":str(self.sdxl)}
        self.generated=None

    def tearDown(self):
        self.tmp.cleanup()

    def register(self):
        item=local_images.register_existing_model(self.jobs,self.settings)
        return item["id"],local_images.get(self.jobs,item["id"])

    def test_sdxl_catalog_preserves_existing_qwen(self):
        ident,profile=self.register()
        self.assertTrue(local_images._profile_good(profile))
        self.assertEqual(profile["family"],"sdxl")
        self.assertEqual(profile["steps"],28)
        self.assertEqual(profile["cfg_scale"],7.0)
        self.assertEqual(profile["args"],["--backend","vulkan1","--offload-to-cpu","--vae-tiling"])
        models,_=local_images.catalog(self.jobs)
        self.assertEqual([m["family"] for m in models],["qwen_turbo","sdxl"])
        sd=next(m for m in models if m["id"]==ident)
        self.assertTrue(sd["available"])
        self.assertEqual(sd["reference_mode"],"single")
        self.assertTrue(sd["negative"])
        self.assertEqual(sd["steps"],28)
        again=local_images.register_existing_model(self.jobs,self.settings)
        self.assertEqual(again["id"],ident)
        self.assertTrue(again["existing"])
        self.assertEqual(len(local_images._settings(self.jobs)["profiles"]),2)

    def test_sdxl_missing_or_wrong_checkpoint_rejected_without_changing_registry(self):
        for checkpoint in (str(self.root/"missing.safetensors"),str(self.exe)):
            with self.subTest(checkpoint=checkpoint):
                with self.assertRaises(ValueError):
                    local_images.register_existing_model(self.jobs,
                        {**self.settings,"checkpoint":checkpoint})
        self.assertEqual(len(local_images._settings(self.jobs)["profiles"]),1)

    def test_sdxl_command_uses_checkpoint_cfg7_no_qwen_sigmas(self):
        ident,_=self.register()
        args=[]
        @contextlib.contextmanager
        def fake_handoff(*a,**kw):
            yield
        def fake_run(cmd,*,work,**kw):
            args.extend(cmd)
            (Path(work)/"generated_0.png").parent.mkdir(parents=True,exist_ok=True)
            Image.new("RGB",(512,512),(47,147,147)).save(Path(work)/"generated_0.png")
        request={"strata_image_profile":ident,"size":"512x512",
                 "prompt":"masterpiece, 1girl, teal twintails","negative_prompt":"watermark, blurry",
                 "strata_upscale":"off"}
        with patch.object(local_images,"gpu_handoff",fake_handoff),\
             patch.object(local_images,"publish_state",return_value=None),\
             patch.object(local_images,"_run",side_effect=fake_run):
            status=[]
            response=local_images.generate(self.jobs,request,on_status=status.append)
        self.assertEqual(response["size"],"512x512")
        self.assertIn("Local SDXL inference",status)
        self.assertEqual(args[args.index("--model")+1],str(self.sdxl))
        self.assertEqual(args[args.index("--steps")+1],"28")
        self.assertEqual(args[args.index("--cfg-scale")+1],"7.0")
        self.assertEqual(args[args.index("--negative-prompt")+1],"watermark, blurry")
        self.assertFalse(any(x in args for x in ("--llm","--diffusion-model","--vae",
                                                "--ref-image","--sigmas","--flash-attn")))
        self.assertTrue((self.jobs.root/"generated-images"/response["strata"]["image_file"]).is_file())

    def test_sdxl_img2img_uses_init_img_and_denoise_strength(self):
        ident,_=self.register()
        buffer=io.BytesIO()
        Image.new("RGB",(384,256),(26,205,182)).save(buffer,"PNG")
        ref="data:image/png;base64,"+base64.b64encode(buffer.getvalue()).decode()
        args=[]
        @contextlib.contextmanager
        def fake_handoff(*a,**kw):
            yield
        def fake_run(cmd,*,work,**kw):
            args.extend(cmd)
            reference=Path(cmd[cmd.index("--init-img")+1])
            with Image.open(reference) as im:
                self.assertEqual(im.size,(512,512))
            Image.new("RGB",(512,512),(22,33,44)).save(Path(work)/"generated_0.png")
        request={"strata_image_profile":ident,"size":"512x512","prompt":"anime portrait",
                 "strata_upscale":"off","strata_reference_assets":[{"id":"dummy"}],
                 "strata_reference_images":[ref],"strata_denoise_strength":0.7}
        with patch.object(local_images,"gpu_handoff",fake_handoff),\
             patch.object(local_images,"publish_state",return_value=None),\
             patch.object(local_images,"_run",side_effect=fake_run):
            local_images.generate(self.jobs,request)
        self.assertIn("--init-img",args)
        self.assertEqual(args[args.index("--strength")+1],"0.7")
        self.assertNotIn("--ref-image",args)

    def test_sdxl_rejects_qwen_lora_and_second_reference(self):
        ident,_=self.register()
        req={"strata_image_profile":ident,"size":"512x512","strata_upscale":"off",
             "strata_reference_assets":[]}
        with self.assertRaisesRegex(ValueError,"Qwen LoRA"):
            local_images.validate(self.jobs,{**req,"strata_lora_id":"female-anatomy-v3"})
        with self.assertRaisesRegex(ValueError,"reference images"):
            local_images.validate(self.jobs,{**req,"strata_reference_assets":[{},{}]})

    def test_chat_tool_description_is_specific_to_sdxl(self):
        ident,_=self.register()
        coordinator=object.__new__(TurnCoordinator)
        coordinator.store=ChatTurnStore(self.root)
        coordinator.server=SimpleNamespace(
            image_jobs=self.jobs,
            characters=SimpleNamespace(snapshot=lambda:{
                "global":{"chat_image_profile":ident}}))
        request={"session_id":"a"*32,"turn_id":"b"*32,"model":"test-model",
                 "messages":[{"role":"user","content":"绘制一张初音未来的二次元图"}]}
        _,_,payload=coordinator._validate(request)
        description=payload["tools"][0]["function"]["description"]
        self.assertIn("SDXL/Animagine",description)
        self.assertIn("ENGLISH",description)
        self.assertEqual(payload["messages"],request["messages"])


if __name__=="__main__":
    unittest.main()
