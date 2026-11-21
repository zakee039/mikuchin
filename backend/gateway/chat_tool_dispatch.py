"""Strict server-owned OpenAI image-tool schema and decision parser.

Model output is untrusted. It can supply ONLY a natural-language prompt or edit
instruction. All executable choices (profile, size, LoRA, upscale, billing)
come from Mikuchin's persisted user settings and local provider catalog.
"""
from __future__ import annotations
import json
import re

TOOL_SCHEMAS = (
    {"type": "function", "function": {
        "name": "generate_image",
        "description": "Generate a real image when the user wants you to draw/create a picture or illustration. Do NOT call when explaining how to draw, discussing images, denying the request, or creating tables/files.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"prompt": {"type": "string", "description": "Full visual prompt consistent with character, user and conversation context."}},
                       "required": ["prompt"]}}},
    {"type": "function", "function": {
        "name": "edit_image",
        "description": "Edit the most recent successful generated image in THIS conversation, retaining all unmentioned features. Call only when the user actually asks to edit that picture.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"instruction": {"type": "string", "description": "Precise changes to the last image, preserve everything else."}},
                       "required": ["instruction"]}}},
)
CALL_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}\Z")
LEGACY_PROFILE = {"qwen-image-2.1-turbo-official": "local-qwen-official",
                  "qwen-image-2.1-turbo-uncensored": "local-qwen-uncensored"}


class InvalidToolCall(ValueError):
    pass


def parse_decision(data: dict) -> dict:
    """Strictly require finish_reason=tool_calls, exactly one full call and JSON.

    A truncated or fabricated tool-name in plain text never runs an image job.
    """
    if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or len(data["choices"]) != 1:
        raise InvalidToolCall("Official model returned no unique completion")
    choice = data["choices"][0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise InvalidToolCall("Official model returned no assistant message")
    message = choice["message"]
    finish = choice.get("finish_reason")
    calls = message.get("tool_calls") or []
    if finish != "tool_calls":
        if calls:
            raise InvalidToolCall("Incomplete tool call: finish_reason is not tool_calls")
        content = message.get("content")
        if not isinstance(content, str):
            content = "" if content is None else str(content)
        if not content.strip():
            raise InvalidToolCall("Official model returned neither text nor a complete tool call")
        if len(content) > 100_000:
            raise InvalidToolCall("Model text exceeds response limit")
        # A model emitting a tool-looking JSON string has NOT called a tool.
        return {"kind": "text", "text": content}
    if not isinstance(calls, list) or len(calls) != 1:
        raise InvalidToolCall("Only one image tool call per user turn is permitted")
    call = calls[0]
    if not isinstance(call, dict) or call.get("type") != "function":
        raise InvalidToolCall("Invalid tool-call wrapper")
    ident = call.get("id")
    if not isinstance(ident, str) or not CALL_ID.fullmatch(ident):
        raise InvalidToolCall("Missing or malformed tool_call_id")
    function = call.get("function")
    if not isinstance(function, dict):
        raise InvalidToolCall("Missing tool function")
    name = function.get("name")
    expected = {"generate_image": "prompt", "edit_image": "instruction"}.get(name)
    if expected is None:
        raise InvalidToolCall("Unknown tool name is not authorized")
    raw = function.get("arguments")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 24_000:
        raise InvalidToolCall("Tool arguments must be a short JSON object")
    def strict_pairs(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise InvalidToolCall("Repeated tool argument key")
            result[k] = v
        return result
    try:
        args = json.loads(raw, object_pairs_hook=strict_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError) as exc:
        raise InvalidToolCall("Invalid or incomplete tool argument JSON") from exc
    if not isinstance(args, dict) or set(args) != {expected}:
        raise InvalidToolCall("Tool arguments must contain only " + expected)
    text = args[expected]
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 12_000 or "\x00" in text:
        raise InvalidToolCall("Invalid tool prompt/instruction")
    return {"kind": "tool", "name": name, "tool_call_id": ident,
            "arguments": {expected: text.strip()}}


def resolve_image_request(cards, jobs, decision: dict):
    """Freeze a trusted image request and billing classification before dispatch.

    A selected missing profile is never silently substituted with an online one.
    Default on a fresh instance may resolve to the first configured LOCAL model.
    """
    try:
        from . import local_images, image_providers
    except ImportError:
        import local_images, image_providers
    if cards is None or jobs is None:
        raise ValueError("Character/image configuration is unavailable")
    global_settings = cards.snapshot().get("global", {})
    selected = global_settings.get("chat_image_profile", "default")
    selected = LEGACY_PROFILE.get(selected, selected)
    models = local_images.catalog(jobs)[0] + image_providers.catalog(jobs)
    matching = next((m for m in models if m.get("id") == selected and m.get("available")), None)
    if not matching and selected == "default":
        matching = next((m for m in models if m.get("available") and m.get("family") == "qwen_turbo"), None)
    if not matching:
        raise ValueError("先在全局设置中选定可用的生图模型（不会自动改用收费模型）")
    config = global_settings.get("chat_image_settings")
    if not isinstance(config, dict):
        config = {}
    w, h = config.get("width", 768), config.get("height", 768)
    if type(w) is not int or type(h) is not int or not all(256 <= x <= 2048 for x in (w, h)):
        raise ValueError("全局聊天生图尺寸无效")
    upscale = config.get("upscale", "off")
    if upscale not in ("off", "auto", "4x"):
        raise ValueError("全局超分配置无效")
    parameter = "prompt" if decision["name"] == "generate_image" else "instruction"
    prompt = decision["arguments"][parameter]
    request = {"prompt": prompt, "strata_image_profile": matching["id"],
               "size": f"{w}x{h}", "strata_upscale": upscale}
    if matching.get("family") in ("qwen_turbo","sdxl"):
        mode=config.get("runtime_mode","exclusive")
        if mode not in ("exclusive","concurrent"):
            raise ValueError("无效的聊天生图运行方式")
        # Trusted preference only. The regular Image Studio request schema
        # deliberately does not expose this private chat execution mode.
        request["_chat_runtime_mode"]=mode
    steps = config.get("steps")
    if steps is not None:
        if type(steps) is not int or not 1 <= steps <= 100:
            raise ValueError("全局图像步数无效")
        request["steps"] = steps
    lora = config.get("lora_id", "none")
    if lora not in (None, "", "none"):
        if not isinstance(lora, str):
            raise ValueError("全局 LoRA 无效")
        request["strata_lora_id"] = lora
    # Catalog is the only authority on online vs local.
    return request, {"profile": matching["id"], "model_name": matching.get("name", matching["id"]),
                     "online": matching.get("family") == "api",
                     "require_approval": (matching.get("family") == "api" and
                                          matching.get("chat_confirm_each_call",False) is True),
                     "edit_previous": decision["name"] == "edit_image"}
