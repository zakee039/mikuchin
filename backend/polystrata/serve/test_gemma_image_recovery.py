"""Regression tests for Gemma 4 emitting bare first-party image calls."""
import unittest

from serve.frontend import OutputParser
from serve.image_tools import SCHEMA


def parse(text, size=1, tools=None):
    parser = OutputParser(thinking=False, tools=tools, call_format="gemma", stream_tools=True)
    events = []
    for i in range(0, len(text), size):
        events.extend(parser.feed(text[i:i + size]))
    events.extend(parser.finish())
    return events


class BareImageCall(unittest.TestCase):
    def test_missing_wrapper_still_dispatches_image_tool(self):
        for quoted in ('<|"|>', '<|">'):
            for prefix in ("", "call:"):
                raw = ("Saying hello.\n" + prefix + "polystrata__generate_image{" +
                       "character_related=true,edit_previous:false,prompt:" + quoted +
                       "mint-green cat on a cloud {with stars}" + quoted +
                       ",size:" + quoted + "768x768" + quoted +
                       ",style_hint:" + quoted + "anime" + quoted + "}")
                for size in (1, 2, 7, 10000):
                    with self.subTest(quoted=quoted, prefix=prefix, size=size):
                        events = parse(raw, size, [SCHEMA])
                        calls = [e.call for e in events if e.kind == "tool_call"]
                        self.assertEqual(len(calls), 1)
                        self.assertEqual(calls[0].name, "polystrata__generate_image")
                        self.assertEqual(calls[0].arguments["prompt"], "mint-green cat on a cloud {with stars}")
                        self.assertIs(calls[0].arguments["character_related"], True)
                        self.assertEqual("".join(e.text for e in events if e.kind == "content"),
                                         "Saying hello.")

    def test_no_tool_permission_and_quoted_examples(self):
        sample = 'polystrata__generate_image{prompt:<|"|>a cat<|"|>}'
        for text, tools in ((sample, None), ("please call " + sample, [SCHEMA]),
                            ("\x60" + sample + "\x60", [SCHEMA]),
                            ("\x60\x60\x60\n" + sample + "\n\x60\x60\x60", [SCHEMA]),
                            (sample.replace("polystrata__generate_image", "unlisted_tool"), [SCHEMA])):
            with self.subTest(text=text[:35]):
                self.assertFalse([e for e in parse(text, 3, tools) if e.kind == "tool_call"])

    def test_bad_or_incomplete_arguments_are_not_executed(self):
        for args in ("prompt:<|\"|>unfinished", "prompt:<|\"|>cat<|\"|>,unknown:true}",
                     "prompt:<|\"|>cat<|\"|>,character_related:<|\"|>yes<|\"|>}"):
            self.assertFalse([e for e in parse("polystrata__generate_image{" + args, 2, [SCHEMA])
                              if e.kind == "tool_call"])


class XmlImageCall(unittest.TestCase):
    """Screenshot regression: Gemma sometimes writes a self-closing pseudo-call."""

    def test_screenshot_style_call_dispatches_without_showing_markup(self):
        prompt = ("Hatsune Miku in an office, turquoise twintails, black outfit, "
                  "soft skin illumination, anime style --style_hint anime")
        raw = ('正在为你生成一张图片。\n\n'
               '<call:polystrata__generate_image prompt="' + prompt + '" />')
        for step in (1, 2, 3, 13, 99999):
            with self.subTest(chunk_size=step):
                events = parse(raw, step, [SCHEMA])
                calls = [e.call for e in events if e.kind == "tool_call"]
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].name, "polystrata__generate_image")
                self.assertEqual(calls[0].arguments, {"prompt": prompt})
                content = "".join(e.text for e in events if e.kind == "content")
                self.assertEqual(content, "正在为你生成一张图片。")
                self.assertNotIn("<call:", content)

    def test_attributes_and_inner_quote_stay_structured(self):
        raw = ("<call:polystrata__generate_image prompt='two \\\'cats\\\' in a scene' "
               'style_hint="anime" size="768x768" edit_previous="false" '
               'character_related="true" />')
        for chunk in (1, 5, 1024):
            with self.subTest(chunk=chunk):
                calls = [e.call for e in parse(raw, chunk, [SCHEMA]) if e.kind == "tool_call"]
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].arguments["prompt"], "two 'cats' in a scene")
                self.assertIs(calls[0].arguments["character_related"], True)
                self.assertIs(calls[0].arguments["edit_previous"], False)
                self.assertEqual(calls[0].arguments["style_hint"], "anime")

    def test_declared_tool_and_literal_quotes_guard_against_spurious_execution(self):
        sample = '<call:polystrata__generate_image prompt="a cat" />'
        for text, tools in (
            (sample, None),
            (sample, []),
            ("The model might write " + sample, [SCHEMA]),
            ("`" + sample + "`", [SCHEMA]),
            ("```xml\n" + sample + "\n```", [SCHEMA]),
            (sample.replace("polystrata__generate_image", "untrusted_tool"), [SCHEMA]),
        ):
            with self.subTest(text=text[:55]):
                events = parse(text, 1, tools)
                self.assertEqual([e for e in events if e.kind == "tool_call"], [])

    def test_bad_and_truncated_xml_never_start_a_job_or_leak_prompt(self):
        invalid = (
            '<call:polystrata__generate_image prompt="" />',
            '<call:polystrata__generate_image prompt="cat" unknown="yes" />',
            '<call:polystrata__generate_image prompt="cat" prompt="dog" />',
            '<call:polystrata__generate_image prompt="cat" style_hint="bad" />',
            '<call:polystrata__generate_image prompt="cat" edit_previous="yes" />',
            '<call:polystrata__generate_image prompt=cat />',
            '<call:polystrata__generate_image prompt="cat',
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                events = parse(raw, 1, [SCHEMA])
                self.assertFalse([e for e in events if e.kind == "tool_call"])
                self.assertIn("图像任务未创建", "".join(
                    e.text for e in events if e.kind == "content"))
                self.assertNotIn("<call:", "".join(
                    e.text for e in events if e.kind == "content"))

    def test_bare_mapping_invalid_args_have_explicit_not_created_feedback(self):
        events = parse('polystrata__generate_image{prompt:<|"|>cat<|"|>,unknown:true}', 2, [SCHEMA])
        self.assertFalse([e for e in events if e.kind == "tool_call"])
        self.assertIn("图像任务未创建", "".join(
            e.text for e in events if e.kind == "content"))
        cut = parse('polystrata__generate_image{prompt:<|"|>unfinished', 3, [SCHEMA])
        self.assertFalse([e for e in cut if e.kind == "tool_call"])
        self.assertIn("图像任务未创建", "".join(e.text for e in cut if e.kind == "content"))
        self.assertNotIn("polystrata__", "".join(e.text for e in cut if e.kind == "content"))

    def test_recognized_xml_runs_real_image_hub_instead_of_stopping_at_parser(self):
        import contextlib
        import io
        import threading
        from types import SimpleNamespace
        from unittest.mock import patch
        from PIL import Image
        from serve.image_tools import ChatImageHub, NAME
        from serve.server import run_with_mcp

        raw = ('好的，我来画。\n'
               '<call:polystrata__generate_image prompt="a red triangle on white" '
               'upscale="off" style_hint="other" />')
        events = parse(raw, 2, [SCHEMA])

        class FakeImage:
            cfg = {"max_side": 1024, "max_n": 1}
            calls = 0
            def run(self, job, cancel):
                self.calls += 1
                image = io.BytesIO()
                Image.new("RGB", (16, 16), "red").save(image, "PNG")
                return [image.getvalue()], {"seconds": 0}
            def store(self, image):
                return "a" * 32 + ".png"

        class FakeService:
            images = FakeImage()
            session_v1 = None
            vision = None
            turns = 0
            def run(self, *args, **kwargs):
                self.turns += 1
                for event in events:
                    yield "event", event
                yield "done", {"completion_tokens": 43, "prompt_tokens": 21, "finish": "stop"}
            def prepare(self, *args, **kwargs):
                raise AssertionError("Image success must not cause a second image-tool round")

        @contextlib.contextmanager
        def fake_gpu_turn(*args, **kwargs):
            yield "unload"

        svc = FakeService()
        hub = ChatImageHub(svc)
        with patch("serve.image_tools.images_api.gpu_turn", fake_gpu_turn):
            output = list(run_with_mcp(svc, hub, [], [SCHEMA], {}, [1], False,
                                       128, 128, {}, threading.Event(), {NAME}))
        self.assertEqual(svc.images.calls, 1)
        self.assertEqual(svc.turns, 1)
        results = [entry for kind, entry in output
                   if kind == "mcp" and entry.get("event") == "result"]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"], results[0])
        self.assertEqual(results[0]["image_file"], "a" * 32 + ".png")
        self.assertEqual(output[-1][0], "done")
        self.assertNotIn("<call:", "".join(
            e.text for kind, e in output if kind == "event" and e.kind == "content"))

    def test_unexpected_image_provider_exception_has_terminal_failure_event(self):
        import threading
        from types import SimpleNamespace
        from serve.image_tools import NAME
        from serve.server import run_with_mcp
        from serve.frontend import Event

        events = parse('<call:polystrata__generate_image prompt="cat" />', 1, [SCHEMA])

        class FakeService:
            turns = 0
            def run(self, *args, **kwargs):
                self.turns += 1
                for event in events:
                    yield "event", event
                yield "done", {"completion_tokens": 12, "finish": "stop"}
            def prepare(self, *args, **kwargs):
                raise AssertionError("Failed image generation must not retry")

        class FailedHub:
            settings = {"max_rounds": 8}
            def routes(self):
                return {NAME: (SimpleNamespace(name="PolyStrata"), "generate_image")}
            def call(self, *args):
                raise OSError("simulated image backend failure")

        svc = FakeService()
        output = list(run_with_mcp(svc, FailedHub(), [], [SCHEMA], {}, [1], False,
                                   128, 128, {}, threading.Event(), {NAME}))
        results = [entry for kind, entry in output
                   if kind == "mcp" and entry.get("event") == "result"]
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIn("tool execution failed", results[0]["text"])
        self.assertNotIn("image_file", results[0])
        self.assertEqual(svc.turns, 1)
        self.assertTrue(any(kind == "event" and item.kind == "content" and "图像生成失败" in item.text
                            for kind, item in output if kind == "event"))


if __name__ == "__main__":
    unittest.main()
