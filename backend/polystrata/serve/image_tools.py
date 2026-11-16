"""Built-in image tool for PolyStrata's opt-in web chat.

Shares the ImageGen backend and GPU turn with POST /v1/images/generations. The
external MCP hub remains independent; the tool is exposed only when the user's
own chat page opts in and the image backend has been configured.
"""
from __future__ import annotations

import threading
import time
import re
from pathlib import Path
from types import SimpleNamespace

from serve import images as images_api

NAME = "polystrata__generate_image"
# Visual references must not be injected into every subsequent conversation
# turn: Gemma charges image tokens and an unrelated scene could mislead it.
# An explicit picture reference works even after several turns; otherwise
# visual attributes apply only within the first three follow-up user turns.
IMAGE_EXPLICIT = re.compile(
    r"图片|照片|图中|图里|图上|这张|那张|上一张|刚才画|刚画|画出来|生图|生成的图|"
    r"画的|画好了|图像|原图|改图|修图|重画|画面|插画|pic(?:ture)?|image|photo|"
    r"draw(?:ing)?|illustration|render|edit (?:it|this|the)|previous one",
    re.IGNORECASE)
IMAGE_VISUAL = re.compile(
    r"眼睛|瞳孔|睫毛|鼻子|嘴巴|脸|表情|外套|衣服|裙子|服装|穿着|穿的|"
    r"头发|发色|马尾|发型|耳朵|帽子|袖子|领口|鞋子|裙摆|手臂|腿|姿势|"
    r"背景|颜色|色调|光影|细节|构图|太大|太小|大一点|小一点|更大|更小|"
    r"再大|再小|漂亮|好看|可爱|好美|眼神|动作|修改|调整|改一下|"
    r"coat|jacket|dress|shirt|outfit|wearing|eyes?|hair|face|pose|"
    r"background|color|bigger|smaller|prett(?:y|ier)|beautiful|cute|"
    r"make it|change (?:it|them|the)",
    re.IGNORECASE)
IMAGE_CHANGE = re.compile(
    r"改一下|改成|修改|调整|调一调|修图|修正|放大|缩小|更大|更小|大一点|小一点|"
    r"大点|小点|再大|再小|去掉|删掉|加上|换成|换个|变大|变小|"
    r"edit|adjust|change|make .{0,24}bigger|make .{0,24}smaller|remove|replace",
    re.IGNORECASE)
FRESH_IMAGE = re.compile(r"重新画一张|再画一张|另画一张|新画一张|生成一张新的|再来一张|new picture|new image",
                         re.IGNORECASE)


def needs_recent_image(text, user_turns_since: int) -> bool:
    """Whether the user likely points at their own previously generated art."""
    if not isinstance(text, str) or not text.strip():
        return False
    if IMAGE_EXPLICIT.search(text):
        return True
    return 0 <= user_turns_since <= 3 and bool(IMAGE_VISUAL.search(text))


def clearly_editing_recent_image(text, user_turns_since: int) -> bool:
    """Conservative safety net when a model omits the edit_previous argument."""
    return (needs_recent_image(text, user_turns_since) and bool(IMAGE_CHANGE.search(text))
            and not bool(FRESH_IMAGE.search(text)))


def add_relevant_image(svc, session_id, messages, *, stateless=False):
    """Offer the most recent picture as *temporary* visual context, when relevant.

    No data URL is placed in the saved chat. File provenance comes from the
    server-owned SessionV1 conversation, never from a request field. A later
    user turn without visual intent is completely unchanged.
    """
    if (stateless or not session_id or not getattr(svc, "vision", None) or
            not getattr(getattr(svc, "session_v1", None), "recent_generated_image", None) or not messages):
        return messages
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return messages
    content = last.get("content")
    if isinstance(content, list):
        if any(isinstance(part, dict) and part.get("type") == "image" for part in content):
            return messages  # the user already supplied a visual reference
        text = " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    elif isinstance(content, str):
        text = content
    else:
        return messages
    recent = svc.session_v1.recent_generated_image(session_id)
    if not recent or not needs_recent_image(text, recent["user_turns_since"]):
        return messages
    parts = list(content) if isinstance(content, list) else [{"type": "text", "text": content}]
    parts.append({"type": "image", "source": str(recent["path"])})
    # This is an internally resolved file, appended *after* the public API's
    # local-image authorization check. Never persist it as the user's message.
    return [*messages[:-1], {**last, "content": parts}]
SCHEMA = {
    "name": NAME,
    "description": ("Generate a new picture, or edit the latest generated picture "
                    "in this conversation when the user asks for a change such as larger eyes. "
                    "For modifications of the previous picture, set edit_previous=true; "
                    "preserve everything the user did not ask to change. "
                    "Do not use it for ordinary questions or compliments. The "
                    "result is inserted automatically into the chat by PolyStrata. "
                    "Write a visual prompt faithful to the user's request; do not "
                    "invent clothing, intimacy, pose, or scene details they did not ask for. "
                    "Invoke the declared tool rather than writing tool-call syntax "
                    "in your conversational response; plain text never creates an image task. "
                    "Use 768x768 by default. Respect the user's request to disable "
                    "upscaling, and identify anime styles with style_hint=anime."),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The scene or picture to generate."},
            "size": {"type": "string", "enum": ["512x512", "768x768", "1024x1024"],
                     "description": "Default 768x768. Larger sizes use more resources."},
            "upscale": {"type": "string", "enum": ["auto", "off", "4x"],
                        "description": "Default auto. Anime pictures get 4x upscaling; off disables it."},
            "style_hint": {"type": "string", "enum": ["auto", "anime", "other"],
                           "description": "Anime only when clearly an anime/2D Japanese animation style."},
            "character_related": {"type": "boolean", "description": (
                "Set true only when the image subject is the chat's assigned character. "
                "Never apply the character reference image to unrelated image subjects. "
                "Follow the user's latest and earlier instructions above the reference image.")},
            "edit_previous": {"type": "boolean", "description": (
                "Set true ONLY when the user asks to change an image already generated in this "
                "conversation (e.g. make the eyes larger). The previous picture becomes the "
                "strong image reference. Leave false for a new picture or ordinary dialogue.")},
        },
        "required": ["prompt"],
    },
}


class ChatImageHub:
    """MCP-compatible adapter so image tools join, not replace, existing MCP."""

    def __init__(self, svc, mcp=None, *, session_id=None, stateless=False, latest_user_text=""):
        self.svc, self.mcp = svc, mcp
        self.session_id = session_id if not stateless else None
        self.latest_user_text = latest_user_text if isinstance(latest_user_text, str) else ""
        self.character_name = None
        self.character_reference = None
        self.recent_image = None
        self.gen = getattr(svc, "images", None)
        self.remote_id = None
        self.profile_id = self.gen.cfg.get("profile_id", "default") if self.gen else "default"
        self.chat_image_settings = None
        cards = None
        if getattr(svc, "session_v1", None) is not None:
            from serve.character_cards import CharacterStore
            cards = CharacterStore(svc.session_v1.root.parent / "character")
            self.chat_image_settings = cards.chat_image_settings()
            selected = cards.chat_image_profile()
            profiles = getattr(svc, "image_profiles", {})
            if selected in ("default", self.profile_id) and self.gen is not None:
                self.profile_id = self.gen.cfg.get("profile_id", "default")
            elif selected in profiles:
                self.gen = profiles[selected]
                self.profile_id = selected
            elif isinstance(selected, str) and selected.startswith("api-"):
                from serve import image_api_services
                if image_api_services.get(svc, selected):
                    self.remote_id = selected
                    self.profile_id = selected
            # Obsolete profile settings fall back to the current default.
        # Resolve per request so saving a new choice takes effect immediately.

        # Reference images are server-owned, never inferred from client paths.
        # No character identity or image in the stateless/ordinary assistant.
        if not stateless and session_id and getattr(svc.session_v1, "recent_generated_image", None):
            self.recent_image = svc.session_v1.recent_generated_image(session_id)
        if not stateless and session_id and cards is not None:
            card = cards.assigned_card(session_id)
            if card and card.get("reference_image"):
                file = cards.image_file(card["id"])
                if file and file.stat().st_size <= 5 * 1024 * 1024:
                    self.character_name = card["name"]
                    self.character_reference = file
        self.settings = {**(mcp.settings if mcp else {}), "max_rounds":
                         int((mcp.settings if mcp else {}).get("max_rounds", 8))}
        self.builtin = SimpleNamespace(name="PolyStrata", status="ready")

    def wait(self, timeout):
        if self.mcp:
            self.mcp.wait(timeout)

    def routes(self):
        routes = dict(self.mcp.routes()) if self.mcp else {}
        if self.gen is not None or self.remote_id is not None:
            routes[NAME] = (self.builtin, "generate_image")
        return routes

    def template_tools(self, exclude=()):
        tools = list(self.mcp.template_tools(exclude=exclude)) if self.mcp else []
        if (self.gen is not None or self.remote_id is not None) and NAME not in exclude:
            tools = [tool for tool in tools if tool.get("name") != NAME]
            if self.gen is not None and self.character_reference is not None and self.gen.cfg.get("family", "qwen_turbo") == "qwen_turbo" and self.gen.cfg.get("llm_vision"):
                tool = {**SCHEMA, "description": SCHEMA["description"] +
                        f" The current chat character is {self.character_name!r}, and a weak appearance reference is available."}
            else:
                tool = SCHEMA
            if self.recent_image is not None:
                tool = {**tool, "description": tool["description"] +
                        " A previously generated image is available in THIS chat; "
                        "use edit_previous=true for changes to it."}
            # Adapt the tool's visual prompt style to the selected backend.
            if self.gen is not None and self.gen.cfg.get("family") == "sdxl":
                tool = {**tool, "description": tool["description"] +
                        " For this SDXL model, write concise ENGLISH descriptive phrases "
                        "or anime tags where appropriate; include the user's specified "
                        "scene, costume, pose and holiday exactly."}
            if self.remote_id is not None:
                from serve import image_api_services
                remote = image_api_services.get(self.svc, self.remote_id)
                preset = remote.get("sizes", "standard") if remote else "standard"
                sizes = (["1024x1024"] if preset == "square" else
                         ["1024x1024", "1024x1536", "1536x1024"] if preset == "standard"
                         else ["512x512", "768x768", "1024x1024", "1024x1536", "1536x1024"])
                params = {**tool["parameters"], "properties": dict(tool["parameters"]["properties"])}
                params["properties"]["size"] = {"type": "string", "enum": sizes,
                                               "description": "Default 1024x1024."}
                params["properties"].pop("upscale", None)  # local enhancement only
                tool = {**tool, "parameters": params,
                        "description": tool["description"].replace(
                            "Use 768x768 by default.", "Use 1024x1024 by default.")}
            tools.append(tool)
        return tools

    def _remote_call(self, arguments, cancel=None):
        """Generate chat images with a configured OpenAI Images provider."""
        import base64
        from io import BytesIO
        from PIL import Image, ImageOps
        from serve import image_api_services
        start = time.monotonic()
        output = {"server": "Mikuchin", "tool": "generate_image", "truncated": False}
        try:
            if not isinstance(arguments, dict) or not isinstance(arguments.get("prompt"), str):
                raise ValueError("image prompt must be a string")
            if cancel and cancel.is_set():
                raise RuntimeError("image generation cancelled")
            service = image_api_services.get(self.svc, self.remote_id)
            if not service:
                raise ValueError("selected API image service is missing")
            sizes = {"square": (1024,), "standard": (1024, 1536),
                     "all": (384, 512, 768, 1024, 1536)}[service["sizes"]]
            requested = arguments.get("size") or "1024x1024"
            try:
                w, h = (int(n) for n in requested.split("x"))
            except (ValueError, AttributeError):
                w = h = 1024
            if w not in sizes or h not in sizes:
                w = h = 1024 if 1024 in sizes else sizes[0]
            request = {
                "prompt": arguments["prompt"], "size": f"{w}x{h}", "n": 1,
                "response_format": "url",
            }
            if self.chat_image_settings:
                preset = self.chat_image_settings
                w, h = preset.get("width"), preset.get("height")
                if w in sizes and h in sizes:
                    request["size"] = f"{w}x{h}"
                if service["steps"] and isinstance(preset.get("steps"), int):
                    request["steps"] = preset["steps"]

            edit_previous = (arguments.get("edit_previous") is True or
                             (self.recent_image is not None and
                              clearly_editing_recent_image(self.latest_user_text,
                                                            self.recent_image["user_turns_since"])))
            ref_file = None
            if edit_previous:
                if not self.recent_image:
                    raise ValueError("no prior generated image to edit in this conversation")
                ref_file = self.recent_image["edit_path"]
                request["prompt"] = ("Edit the provided image: " + request["prompt"] +
                                     "\nPreserve all visual details not explicitly changed.")
            elif arguments.get("character_related") is True and self.character_reference is not None:
                ref_file = self.character_reference
                request["prompt"] += (
                    "\nCharacter reference is for identity only. The user's scene, "
                    "outfit, pose, colors and holiday instructions take precedence.")
            if ref_file is not None and service["reference_mode"] != "none":
                with Image.open(ref_file) as img:
                    img = ImageOps.exif_transpose(img).convert("RGB")
                    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                if buf.tell() > 5 * 1024 * 1024:
                    raise ValueError("reference image exceeds 5 MB")
                request["strata_reference_images"] = [
                    "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")]
            result = image_api_services.generate(self.svc, request, ident=self.remote_id)
            filename = result["strata"].get("image_file")
            if not filename:
                raise RuntimeError("API image was not persisted")
            output.update({
                "image_file": filename,
                "image_profile": self.remote_id,
                "image_model": service["model"],
                "image_prompt": str(arguments["prompt"]),
                "edited_previous": edit_previous,
                "character_reference_used": bool(ref_file and not edit_previous
                                                  and service["reference_mode"] != "none"),
                "upscale_applied": False,
                "ok": True,
                "text": "Generated the requested image successfully using the API service. "
                        "The image is already displayed in this conversation; do not generate it again.",
            })
            if self.session_id and getattr(self.svc.session_v1, "register_generated_image", None):
                self.svc.session_v1.register_generated_image(self.session_id, filename, None)
            try:
                from serve import gallery as gallery_api
                gallery_api.register(self.svc, filename, source="chat", provider="api",
                    model=service["model"], prompt=arguments.get("prompt",""),
                    session_id=self.session_id or "")
                for original in result["strata"].get("upscale_original_files") or []:
                    if original:
                        gallery_api.register(self.svc, original, source="chat", provider="api",
                            model=service["model"], prompt=arguments.get("prompt",""),
                            session_id=self.session_id or "", parent_id=filename[:-4])
            except Exception as gallery_exc:
                print(f"[mikuchin] gallery chat API index failed: {gallery_exc}", flush=True)
        except Exception as exc:
            output["ok"] = False
            output["text"] = "error: API image generation failed: " + str(exc)[:500]
        output["chars"] = len(output["text"])
        output["ms"] = int((time.monotonic() - start) * 1000)
        return output

    def call(self, name, arguments, cancel: threading.Event | None = None):
        if name != NAME:
            return self.mcp.call(name, arguments, cancel)
        if self.remote_id is not None:
            return self._remote_call(arguments, cancel)
        start = time.monotonic()
        output = {"server": "PolyStrata", "tool": "generate_image", "truncated": False}
        try:
            if self.gen is None:
                raise ValueError("image generation is not enabled")
            if callable(getattr(self.gen, "missing", None)) and self.gen.missing():
                raise ValueError("selected chat image model files are missing")
            if not isinstance(arguments, dict):
                raise ValueError("expected image arguments as an object")
            request = {
                "prompt": arguments.get("prompt"), "size": arguments.get("size") or "768x768",
                "n": 1, "response_format": "url",
                "strata_upscale": arguments.get("upscale") or "auto",
                "strata_style_hint": arguments.get("style_hint") or "auto",
            }
            if self.chat_image_settings is not None:
                # Server-owned chat preset has precedence over the LLM's
                # suggestions. No paths or unregistered LoRAs enter the job.
                from serve.character_cards import CharacterStore
                preset = CharacterStore.validate_chat_image_settings(
                    self.chat_image_settings, self.gen.cfg)
                request["size"] = f"{preset['width']}x{preset['height']}"
                request["strata_upscale"] = preset["upscale"]
                if preset["steps"] is not None:
                    request["steps"] = preset["steps"]
                if preset["lora_id"] != "none":
                    request["strata_lora_id"] = preset["lora_id"]
            edit_previous = (arguments.get("edit_previous") is True or
                             (self.recent_image is not None and
                              clearly_editing_recent_image(self.latest_user_text,
                                                            self.recent_image["user_turns_since"])))
            if edit_previous:
                # Only session-owned, validated image history may provide a
                # reference. Never open a client-supplied filename or path.
                if not self.recent_image:
                    raise ValueError("there is no previous generated picture in this conversation to edit")
                if self.gen.cfg.get("family", "qwen_turbo") != "sdxl" and not self.gen.cfg.get("llm_vision"):
                    raise ValueError("the selected image model cannot edit a reference picture")
                import base64
                from io import BytesIO
                from PIL import Image, ImageOps
                with Image.open(self.recent_image["edit_path"]) as src:
                    src = ImageOps.exif_transpose(src).convert("RGB")
                    src.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    data = BytesIO()
                    src.save(data, format="PNG", optimize=True)
                if data.tell() > 5 * 1024 * 1024:
                    raise ValueError("previous picture is too large for the reference-image encoder")
                request["strata_reference_image"] = ("data:image/png;base64," +
                                                       base64.b64encode(data.getvalue()).decode("ascii"))
                request["prompt"] = ("Edit the provided image: " + str(arguments.get("prompt") or "") +
                                     "\nPreserve the character identity, colors, composition and every detail "
                                     "not explicitly requested to change. The source picture is authoritative.")
            character_related = arguments.get("character_related") is True
            if not edit_previous and character_related and self.character_reference is not None and self.gen.cfg.get("family", "qwen_turbo") == "qwen_turbo" and self.gen.cfg.get("llm_vision"):
                import base64
                # Weak reference: never overwrite explicit scene, costume, pose,
                # calendar/holiday or subject instructions from the conversation.
                request["prompt"] = (str(arguments.get("prompt") or "") +
                    "\nReference photo is for this character's visual identity only. "
                    "Treat the text request as authoritative for the subject, "
                    "scene, holiday, outfit, colors, actions, pose, composition and "
                    "any conflicting details. Never copy unrelated scene or attire from the reference.")
                request["strata_reference_image"] = ("data:image/png;base64," +
                    base64.b64encode(self.character_reference.read_bytes()).decode("ascii"))
            job = images_api.parse_request(request, self.gen.cfg)
            if "strata_reference_image" in request and not edit_previous:
                job["character_weak_reference"] = True
            if cancel and cancel.is_set():
                raise RuntimeError("image generation cancelled")
            gen = self.gen
            if self.svc.session_v1:
                gen.dir = self.svc.session_v1.root / "generated-images"
                gen.dir.mkdir(parents=True, exist_ok=True)
                gen.keep_files = 2**31 - 1
            with images_api.gpu_turn(self.svc, gen, job, cancel) as policy:
                images, figures = gen.run(job, cancel)
                images, up = images_api.postprocess(gen, images, job, cancel)
                figures.update(up)
            filename = gen.store(images[0])
            output["image_file"] = filename
            output["image_profile"] = self.profile_id
            output["image_model"] = getattr(gen, "model", self.profile_id)
            output["image_prompt"] = str(arguments.get("prompt") or "")
            output["edited_previous"] = edit_previous
            output["character_reference_used"] = bool(job.get("character_weak_reference"))
            if figures.get("upscale_original_files"):
                output["image_original_file"] = figures["upscale_original_files"][0]
            output["upscale_applied"] = figures.get("upscale_applied", False)
            output["upscale_reason"] = figures.get("upscale_reason", "")
            if figures.get("upscale_fallback"):
                output["upscale_fallback"] = True
            if self.session_id and getattr(self.svc.session_v1, "register_generated_image", None):
                self.svc.session_v1.register_generated_image(
                    self.session_id, filename, output.get("image_original_file"))
            try:
                from serve import gallery as gallery_api
                gallery_api.register(self.svc, filename, source="chat", provider="local",
                    model=output.get("image_model",""), prompt=arguments.get("prompt",""),
                    session_id=self.session_id or "")
                if output.get("image_original_file"):
                    gallery_api.register(self.svc, output["image_original_file"],
                        source="chat", provider="local",
                        model=output.get("image_model",""), prompt=arguments.get("prompt",""),
                        session_id=self.session_id or "", parent_id=filename[:-4])
            except Exception as gallery_exc:
                print(f"[mikuchin] gallery chat local index failed: {gallery_exc}", flush=True)
            output["text"] = (f"Generated the requested image successfully "
                              f"(size {figures.get('upscale_output_size') or str(job['width'])+'x'+str(job['height'])}, "
                              f"seed {job['seed']}, "
                              f"GPU policy {policy}). The image is already displayed "
                              "in this conversation; do not generate it again."
                              + (" Anime 4x upscale failed; showing the original picture."
                                 if figures.get("upscale_fallback") else ""))
            output["ok"] = True
        except Exception as exc:
            output["ok"] = False
            output["text"] = f"error: image generation failed: {str(exc)[:500]}"
            if self.gen is not None and hasattr(self.gen, "_say"):
                self.gen._say(f"chat image tool failed: {type(exc).__name__}: {str(exc)[:240]}")
        output["chars"] = len(output["text"])
        output["ms"] = int((time.monotonic() - start) * 1000)
        return output
