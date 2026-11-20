"""Native local image model/LoRA/4x and OS GPU gate regression tests.

All subprocesses are fake test binaries; no paid API, model weights or GPU used.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from backend.gateway import gallery, local_images
from backend.gateway.gpu_gate import GPUUnavailable, gpu_turn
from backend.gateway.image_jobs import ImageJobStore


def png(size):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


class NativeGpuGateTests(unittest.TestCase):
    def test_shared_inference_may_coexist_but_exclusive_image_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            with gpu_turn(directory, timeout=.5):
                with gpu_turn(directory, timeout=.5):
                    with self.assertRaises(GPUUnavailable):
                        with gpu_turn(directory, exclusive=True, timeout=.13):
                            self.fail("writer entered alongside active readers")
            with gpu_turn(directory, exclusive=True, timeout=.5):
                with self.assertRaises(GPUUnavailable):
                    with gpu_turn(directory, timeout=.13):
                        self.fail("reader entered alongside exclusive image turn")
            with gpu_turn(directory, timeout=.5):
                pass

    def test_gate_works_across_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ("import sys; from backend.gateway.gpu_gate import gpu_turn, GPUUnavailable; "
                    "p=sys.argv[1]; "
                    "\ntry:\n with gpu_turn(p,timeout=.15):\n  print('ENTERED')"
                    "\nexcept GPUUnavailable:\n print('BUSY')\n")
            with gpu_turn(directory, exclusive=True):
                child = subprocess.run([sys.executable, "-B", "-c", code, directory],
                                       cwd=str(Path(__file__).resolve().parents[2]),
                                       capture_output=True, text=True, timeout=7)
                self.assertEqual(child.returncode, 0, child.stderr)
                self.assertEqual(child.stdout.strip(), "BUSY")
            child = subprocess.run([sys.executable, "-B", "-c", code, directory],
                                   cwd=str(Path(__file__).resolve().parents[2]),
                                   capture_output=True, text=True, timeout=7)
            self.assertEqual(child.stdout.strip(), "ENTERED", child.stderr)


class LocalNativeImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.jobs = ImageJobStore(self.root / "images", embedded_worker=True)
        source = self.root / "fake-model"
        source.mkdir()
        for name in ("sd-cli.exe", "qwen.gguf", "vae.safetensors", "llm.gguf",
                     "lora.safetensors", "realesrgan.exe", "realesrgan-x4plus-anime.bin",
                     "realesrgan-x4plus-anime.param"):
            (source / name).write_bytes(b"test")
        self.config = {
            "profiles": [{"id":"local-qwen-test", "name":"Local fake Qwen",
                          "family":"qwen_turbo", "model":"test-qwen",
                          "exe":str(source/"sd-cli.exe"), "diffusion_model":str(source/"qwen.gguf"),
                          "llm":str(source/"llm.gguf"), "vae":str(source/"vae.safetensors"),
                          "max_side":1024, "args":["--offload-to-cpu"]}],
            "loras": [{"id":"lora-test","name":"Fake LoRA","path":str(source/"lora.safetensors")}],
            "upscaler": {"enabled":True, "exe":str(source/"realesrgan.exe"),
                         "model_dir":str(source), "model":"realesrgan-x4plus-anime",
                         "max_output_side":3072},
        }
        folder = local_images.config_path(self.jobs)
        folder.parent.mkdir(parents=True)
        folder.write_text(json.dumps(self.config), encoding="utf-8")
        self.req = {"prompt":"A small anime cat", "size":"384x384",
                    "strata_image_profile":"local-qwen-test", "strata_upscale":"off",
                    "strata_lora_id":"lora-test"}

    def tearDown(self):
        self.jobs.queue.join()
        self.temp.cleanup()

    def test_catalog_and_validation_reject_unregistered_lora_and_large_4x(self):
        models, loras = local_images.catalog(self.jobs)
        self.assertTrue(models[0]["available"])
        self.assertTrue(models[0]["upscale_available"])
        self.assertTrue(loras[0]["available"])
        self.assertEqual(local_images.validate(self.jobs, self.jobs._prepare(self.req))["id"],
                         "local-qwen-test")
        with self.assertRaisesRegex(ValueError,"LoRA"):
            self.jobs._require_provider(self.jobs._prepare({**self.req,"strata_lora_id":"invalid"}))
        with self.assertRaisesRegex(ValueError,"4x output"):
            self.jobs._require_provider(self.jobs._prepare({**self.req,
                "strata_upscale":"4x","size":"1024x1024"}))
        with self.assertRaisesRegex(ValueError,"divisible by 32"):
            self.jobs._require_provider(self.jobs._prepare({**self.req,"size":"400x400"}))

    def test_generate_is_independent_of_online_api_and_registers_gallery(self):
        seen = []
        def fake_run(args, *, work, **kwargs):
            seen.append(args)
            (Path(work)/"generated_0.png").write_bytes(png((384,384)))
        with mock.patch.object(local_images,"gpu_handoff",side_effect=lambda *a, **k: contextlib.nullcontext()), \
             mock.patch.object(local_images,"_run",side_effect=fake_run):
            task = self.jobs.submit({"request":self.req})
            self.jobs.queue.join()
        result = self.jobs.listing(task["id"])
        self.assertEqual(result["state"],"success",result["error"])
        self.assertEqual(result["result"]["provider"],"local")
        self.assertIn("--lora-model-dir",seen[0])
        self.assertTrue(any("<lora:lora:1>" in arg for arg in seen[0]))
        self.assertEqual(gallery.detail(self.jobs,result["result"]["image_ids"][0])["provider"],"local")

    def test_native_4x_pairs_original_and_cover_without_repeating_generation(self):
        steps = []
        def fake_run(args, *, work, **kwargs):
            if "-n" in args:
                steps.append("upscale")
                with Image.open(Path(work)/"original.png") as img:
                    img.resize((1536,1536)).save(Path(work)/"upscaled.png")
            else:
                steps.append("generate")
                (Path(work)/"generated_0.png").write_bytes(png((384,384)))
        with mock.patch.object(local_images,"gpu_handoff",side_effect=lambda *a, **k: contextlib.nullcontext()), \
             mock.patch.object(local_images,"_run",side_effect=fake_run):
            task = self.jobs.submit({"request":{**self.req,"strata_upscale":"4x"}})
            self.jobs.queue.join()
        complete=self.jobs.listing(task["id"])
        self.assertEqual(steps,["generate","upscale"])
        self.assertEqual(complete["state"],"success",complete["error"])
        self.assertTrue(complete["result"]["upscale_applied"])
        cover=gallery.detail(self.jobs,complete["result"]["image_ids"][0])
        self.assertEqual(cover["variant_count"],2)
        self.assertEqual((cover["width"],cover["height"]),(1536,1536))

    def test_upscaler_failure_preserves_successful_original(self):
        def fake_run(args, *, work, **kwargs):
            if "-n" in args:
                raise local_images.LocalImageError("fake upscale fault")
            (Path(work)/"generated_0.png").write_bytes(png((384,384)))
        with mock.patch.object(local_images,"gpu_handoff",side_effect=lambda *a, **k: contextlib.nullcontext()), \
             mock.patch.object(local_images,"_run",side_effect=fake_run):
            task = self.jobs.submit({"request":{**self.req,"strata_upscale":"4x"}})
            self.jobs.queue.join()
        result=self.jobs.listing(task["id"])
        self.assertEqual(result["state"],"success",result["error"])
        self.assertFalse(result["result"]["upscale_applied"])
        self.assertEqual(result["result"]["upscale_warning"],"LocalImageError")
        self.assertTrue(gallery.detail(self.jobs,result["result"]["image_ids"][0]))


if __name__ == "__main__":
    unittest.main()
