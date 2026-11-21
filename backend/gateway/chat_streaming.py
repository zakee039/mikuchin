"""Validated incremental OpenAI SSE assembly for Mikuchin image-tool decisions.

Only text/reasoning deltas may be shown before a full, validated completion.
Partial tool arguments, names and IDs are never executed or exposed as events.
"""
from __future__ import annotations
import json

class StreamIncomplete(ValueError):
    pass

class ToolStreamAssembler:
    def __init__(self):
        self.content=[]
        self.reasoning=[]
        self.calls={}
        self.finish=None
        self.done=False
        self.usage=None
        self.events=0
        self.bytes=0
        self.content_chars=0
        self.reasoning_chars=0

    def consume(self, line):
        """Consume one 'data:' SSE line; return safe deltas or None."""
        if isinstance(line,bytes):
            self.bytes+=len(line)
            if self.bytes>4*1024*1024:raise StreamIncomplete("Model stream exceeds limit")
            line=line.decode("utf-8","strict")
        line=line.strip()
        if not line or line.startswith(":"):return None
        if not line.startswith("data:"):return None
        data=line[5:].strip()
        if data=="[DONE]":
            self.done=True
            return None
        try: obj=json.loads(data)
        except (ValueError,TypeError) as exc:
            raise StreamIncomplete("Malformed official SSE event") from exc
        if not isinstance(obj,dict) or "error" in obj:
            raise StreamIncomplete("Official engine streaming error")
        if obj.get("usage"):self.usage=obj["usage"]
        choices=obj.get("choices") or []
        if not choices:return None
        if not isinstance(choices,list) or len(choices)!=1 or choices[0].get("index",0)!=0:
            raise StreamIncomplete("Unexpected multiple streaming completions")
        choice=choices[0]
        self.events+=1
        if choice.get("finish_reason") is not None:
            self.finish=choice["finish_reason"]
        delta=choice.get("delta") or {}
        if not isinstance(delta,dict):raise StreamIncomplete("Invalid streamed delta")
        for call in delta.get("tool_calls") or []:
            if not isinstance(call,dict):
                raise StreamIncomplete("Invalid tool call fragment")
            index=call.get("index",0)
            if type(index) is not int or not 0<=index<=4:
                raise StreamIncomplete("Invalid tool call index")
            prev=self.calls.setdefault(index,{"id":"","type":"function",
                "function":{"name":"","arguments":""}})
            if call.get("type") not in (None,"function"):
                raise StreamIncomplete("Invalid tool call type")
            prev["id"]+=call.get("id") or ""
            fn=call.get("function") or {}
            if not isinstance(fn,dict):
                raise StreamIncomplete("Invalid streamed function")
            prev["function"]["name"]+=fn.get("name") or ""
            prev["function"]["arguments"]+=fn.get("arguments") or ""
            if len(prev["function"]["arguments"].encode("utf-8"))>24000:
                raise StreamIncomplete("Tool argument stream exceeds limit")
        text=delta.get("content") or ""
        reason=delta.get("reasoning_content") or ""
        if not isinstance(text,str) or not isinstance(reason,str):
            raise StreamIncomplete("Invalid text/reasoning delta")
        if text:self.content.append(text);self.content_chars+=len(text)
        if reason:self.reasoning.append(reason);self.reasoning_chars+=len(reason)
        if self.content_chars>100000 or self.reasoning_chars>140000:
            raise StreamIncomplete("Model output exceeds limit")
        return {"text":text,"reasoning":reason} if text or reason else None

    def complete(self):
        if not self.done or self.finish is None:
            raise StreamIncomplete("Official stream ended before completion")
        calls=[v for _,v in sorted(self.calls.items())]
        if self.finish!="tool_calls" and calls:
            raise StreamIncomplete("Truncated or inconsistent model tool stream")
        return {"choices":[{"finish_reason":self.finish,
                            "message":{"role":"assistant","content":"".join(self.content),
                                       "reasoning_content":"".join(self.reasoning),
                                       "tool_calls":calls if calls else None}}],
                "usage":self.usage or {}}
