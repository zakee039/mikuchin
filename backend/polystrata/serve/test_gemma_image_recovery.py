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


if __name__ == "__main__":
    unittest.main()
