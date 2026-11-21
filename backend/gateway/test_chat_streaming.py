"""Native Tool Calling SSE contract: partial reasoning, safe tool assembly, no replay."""
import json
import unittest
from unittest.mock import patch
try:
    from .chat_streaming import ToolStreamAssembler, StreamIncomplete
    from .chat_tool_dispatch import parse_decision
except ImportError:
    from chat_streaming import ToolStreamAssembler, StreamIncomplete
    from chat_tool_dispatch import parse_decision


def line(delta=None,finish=None):
    return ("data: "+json.dumps({"choices":[{"index":0,"delta":delta or {},
                      "finish_reason":finish}]})+"\n\n").encode()


class ToolStreamTests(unittest.TestCase):
    def test_reasoning_and_plain_text_incremental(self):
        a=ToolStreamAssembler()
        d=a.consume(line({"reasoning_content":"先分析"}))
        self.assertEqual(d["reasoning"],"先分析")
        self.assertEqual(d["text"],"")
        self.assertEqual(a.consume(line({"content":"回答"}))["text"],"回答")
        a.consume(line(finish="stop"))
        a.consume(b"data: [DONE]\n\n")
        parsed=a.complete()
        self.assertEqual(parse_decision(parsed),{"kind":"text","text":"回答"})
        self.assertEqual(parsed["choices"][0]["message"]["reasoning_content"],"先分析")

    def test_structured_call_fragments_are_not_shown(self):
        a=ToolStreamAssembler()
        self.assertEqual(a.consume(line({"reasoning_content":"我要调用生图工具"}))["reasoning"],"我要调用生图工具")
        self.assertIsNone(a.consume(line({"tool_calls":[{"index":0,"id":"call_",
            "type":"function","function":{"name":"generate_","arguments":'{"prompt":"'}}]})))
        self.assertIsNone(a.consume(line({"tool_calls":[{"index":0,"id":"part",
            "function":{"name":"image","arguments":"Miku插画\"}"}}]})))
        a.consume(line(finish="tool_calls"))
        a.consume(b"data: [DONE]\n\n")
        decision=parse_decision(a.complete())
        self.assertEqual(decision["kind"],"tool")
        self.assertEqual(decision["name"],"generate_image")
        self.assertEqual(decision["arguments"]["prompt"],"Miku插画")

    def test_incomplete_model_stream_refuses_tool(self):
        a=ToolStreamAssembler()
        a.consume(line({"tool_calls":[{"index":0,"id":"call_bad",
            "function":{"name":"generate_image","arguments":'{"prompt":"cat"}'}}]}))
        a.consume(line(finish="tool_calls"))
        with self.assertRaises(StreamIncomplete):a.complete()

    def test_model_error_and_unknown_id_refused(self):
        a=ToolStreamAssembler()
        with self.assertRaises(StreamIncomplete):
            a.consume(b'data: {"error":{"message":"bad secret"}}\n')
        with self.assertRaises(StreamIncomplete):
            a.consume(line({"tool_calls":[{"index":-1}]}))

    def test_bad_multicall_finish_refused(self):
        a=ToolStreamAssembler()
        a.consume(line({"tool_calls":[{"index":0,"function":{"name":"generate_image",
              "arguments":'{"prompt":"cat"}'}}]}))
        a.consume(line(finish="stop"))
        a.consume(b"data: [DONE]\n")
        with self.assertRaises(StreamIncomplete):a.complete()


if __name__=="__main__": unittest.main()
