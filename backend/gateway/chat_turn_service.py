"""Native Gateway orchestration for model-selected image tools.

The official server performs the *decision* only. All GPU or payable effects
happen strictly after its response closes and the shared GPU lock is released.
"""
from __future__ import annotations
import base64
import http.client
import io
import json
import logging
import re
import sqlite3
import threading
import time
from PIL import Image
try:
    from .chat_tool_dispatch import TOOL_SCHEMAS, InvalidToolCall, parse_decision, resolve_image_request
    from .chat_turns import ChatTurnStore, TurnForbidden
    from . import gallery, chat_providers
    from .gpu_gate import gpu_turn, GPUUnavailable
    from .chat_streaming import ToolStreamAssembler, StreamIncomplete
    from .image_tool_feedback import classify_error, FAILURE_INSTRUCTION
except ImportError:
    from chat_tool_dispatch import TOOL_SCHEMAS, InvalidToolCall, parse_decision, resolve_image_request
    from chat_turns import ChatTurnStore, TurnForbidden
    import gallery
    import chat_providers
    from gpu_gate import gpu_turn, GPUUnavailable
    from chat_streaming import ToolStreamAssembler, StreamIncomplete
    from image_tool_feedback import classify_error, FAILURE_INSTRUCTION

LOG = logging.getLogger("mikuchin.gateway.turns")
TURN_FIELDS = frozenset(("session_id","turn_id","messages","model","reasoning_effort",
                         "reasoning_budget_tokens","temperature","top_p","top_k","seed","chat_profile","chat_revision"))
IMAGE_NAME = re.compile(r"[a-f0-9]{32}\.png\Z")


class TurnCoordinator:
    def __init__(self, server, data_dir):
        self.server = server
        self.store = ChatTurnStore(data_dir)
        self._active_visions = set()
        self._lock = threading.Lock()
        self._conversation_decisions={}
        self._stop = threading.Event()
        self._watcher = threading.Thread(target=self._watch, name="native-tool-turn-watch", daemon=True)
        self._watcher.start()

    def close(self):
        self._stop.set()

    def _session_decision_lock(self,session):
        with self._lock:
            return self._conversation_decisions.setdefault(session,threading.RLock())

    def _official(self, payload, timeout=240):
        data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode("utf-8")
        if len(data)>7*1024*1024:
            raise ValueError("Model request too large")
        conn=http.client.HTTPConnection(self.server.upstream_host,self.server.upstream_port,timeout=timeout)
        ticket=self.server.request_monitor.begin("chat")
        root=self.server.image_jobs.root.parent if self.server.image_jobs else None
        status=502
        try:
            with gpu_turn(root,timeout=10):
                try:
                    conn.request("POST","/v1/chat/completions",body=data,headers={
                        "Authorization":"Bearer "+self.server.upstream_key,
                        "Content-Type":"application/json","Accept":"application/json"})
                    res=conn.getresponse()
                    status=res.status
                    raw=res.read(4*1024*1024+1)
                    if len(raw)>4*1024*1024:
                        raise ValueError("Official model response too large")
                finally:
                    conn.close()
            # Shared lock is RELEASED before the caller can dispatch an image.
            if status!=200:
                raise ValueError("Official model unavailable (HTTP "+str(status)+")")
            return json.loads(raw)
        finally:
            self.server.request_monitor.finish(ticket,status=status,
                response_bytes=len(data) if status==200 else 0,
                outcome="completed" if status==200 else "upstream_error")

    def _official_stream(self,payload,on_delta,timeout=240):
        """Stream the real reasoning/text while safely assembling tool calls.

        The GPU shared lease covers the COMPLETE model response. A disconnected
        browser does not interrupt the decision or duplicate a possible job;
        only the final fully-validated tool call may dispatch a task.
        """
        payload={**payload,"stream":True}
        data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode("utf-8")
        if len(data)>7*1024*1024:raise ValueError("Model request too large")
        conn=http.client.HTTPConnection(self.server.upstream_host,self.server.upstream_port,timeout=timeout)
        ticket=self.server.request_monitor.begin("chat")
        root=self.server.image_jobs.root.parent if self.server.image_jobs else None
        result=ToolStreamAssembler()
        status=502
        deliver=True
        try:
            with gpu_turn(root,timeout=10):
                try:
                    conn.request("POST","/v1/chat/completions",body=data,headers={
                        "Authorization":"Bearer "+self.server.upstream_key,
                        "Content-Type":"application/json","Accept":"text/event-stream"})
                    resp=conn.getresponse()
                    status=resp.status
                    if status!=200:
                        raise ValueError("Official model unavailable (HTTP "+str(status)+")")
                    while True:
                        line=resp.readline(131072)
                        if not line:break
                        delta=result.consume(line)
                        if delta and deliver:
                            try:on_delta(delta)
                            except (BrokenPipeError,ConnectionError,OSError):
                                # The UI navigated away; the persisted Turn
                                # must STILL finish exactly once server-side.
                                deliver=False
                        if result.done:break
                finally:conn.close()
            return result.complete()
        finally:
            self.server.request_monitor.finish(ticket,status=status,
                response_bytes=result.bytes,
                outcome="completed" if status==200 and result.done
                         else "upstream_error")

    def _chat_complete(self, payload, ref=None, on_delta=None, timeout=240):
        if ref:
            return chat_providers.complete(self.store.path.parent,ref,payload,self.server.request_monitor,on_delta)
        if on_delta is not None:return self._official_stream(payload,on_delta,timeout=timeout)
        return self._official(payload,timeout=timeout)

    def _validate(self, request):
        if not isinstance(request,dict) or set(request)-TURN_FIELDS:
            raise ValueError("Unsupported model-turn request fields")
        session=self.store.validate_id(request.get("session_id"))
        turn=self.store.validate_id(request.get("turn_id"))
        messages=request.get("messages")
        if not isinstance(messages,list) or not 1<=len(messages)<=160:
            raise ValueError("Invalid message history")
        if any(not isinstance(m,dict) or m.get("role") not in
               ("system","developer","user","assistant","tool") for m in messages):
            raise ValueError("Invalid message role")
        if not any(m.get("role")=="user" for m in messages):
            raise ValueError("A user message is required")
        model=request.get("model")
        if not isinstance(model,str) or not 1<=len(model)<=200:
            raise ValueError("Invalid model")
        effort=request.get("reasoning_effort","none")
        if effort not in ("none","low","medium","high"):
            raise ValueError("Invalid reasoning level")
        limit=request.get("reasoning_budget_tokens",0)
        if type(limit) is not int or not 0<=limit<=16384:
            raise ValueError("Invalid reasoning budget")
        payload={"model":model,"messages":messages,"stream":False,
                 "tool_choice":"auto","parallel_tool_calls":False,
                 "tools":list(TOOL_SCHEMAS),"strata_mcp":False,
                 "reasoning_effort":effort,"reasoning_budget_tokens":limit,
                 # Include enough room for the user's configured thinking
                 # budget AND a complete structured JSON tool call. Truncation
                 # must not be mistaken for an executable tool decision.
                 "max_tokens":min(17024,max(768,limit+512))}
        # SDXL checkpoints need descriptive English phrases / booru-style
        # tags, unlike Qwen-Image's natural-language Turbo prompts. This is
        # tool-specific guidance, not a change to the user's character.
        try:
            from . import local_images
        except ImportError:
            import local_images
        selected=(self.server.characters.snapshot().get("global",{})
                  .get("chat_image_profile","")) if self.server.characters else ""
        image_profile=(local_images.get(self.server.image_jobs,selected)
                       if self.server.image_jobs and isinstance(selected,str)
                       and selected.startswith("local-") else None)
        if image_profile and image_profile.get("family")=="sdxl":
            payload["tools"]=[
                {**spec,"function":{**spec["function"],
                    "description":spec["function"]["description"]+
                    (" For the selected SDXL/Animagine checkpoint, "
                     "describe the visual scene in concise ENGLISH phrases "
                     "or anime tags, preserving explicitly requested "
                     "characters, pose, costume and setting.")}}
                if spec["function"]["name"]=="generate_image" else spec
                for spec in TOOL_SCHEMAS]
        for item in ("temperature","top_p","top_k","seed"):
            if item in request:
                v=request[item]
                if not isinstance(v,(int,float)) or isinstance(v,bool) or not (-1e8 <= v <= 1e8):
                    raise ValueError("Invalid sampling parameter")
                payload[item]=v
        profile=request.get("chat_profile","local")
        if profile!="local":
            ref={"id":profile,"revision":request.get("chat_revision")}
            entry=chat_providers.resolve(self.store.path.parent,ref)
            payload["model"]=entry["model"]
            payload.pop("max_tokens",None)
            if entry.get("max_tokens") is not None:payload["max_tokens"]=entry["max_tokens"]
            payload["_chat_provider"]=ref
            if not entry["tools"]:
                payload.pop("tools",None);payload.pop("tool_choice",None);payload.pop("parallel_tool_calls",None)
            # Reject unsupported attachments before persisting or calling any provider.
            chat_providers._wire_payload(entry,payload)
        return session,turn,payload

    def submit(self, request, *, on_delta=None):
        session,turn,payload=self._validate(request)
        if not self.store.create(session,turn,payload):
            return self.store.public(session,turn,self.server.image_jobs)
        try:
            with self._session_decision_lock(session):
                ref=payload.get("_chat_provider")
                result=self._chat_complete(payload,ref,on_delta) if ref else (
                    self._official_stream(payload,on_delta) if on_delta is not None else self._official(payload))
            # The user may have cancelled while the official model was
            # computing. Its answer must then be discarded, never dispatched.
            if self.store.get(session,turn)["state"]!="deciding":
                return self.store.public(session,turn,self.server.image_jobs)
            decision=parse_decision(result)
            if payload.get("_chat_provider") and decision["kind"]!="text" and not payload.get("tools"):
                raise InvalidToolCall("当前聊天 API 未启用工具调用")
            message=result.get("choices",[{}])[0].get("message") or {}
            reasoning=message.get("reasoning_content") or ""
            if not isinstance(reasoning,str):reasoning=""
            if decision["kind"]=="text":
                self.store.decision_text(session,turn,decision["text"],reasoning)
                return self.store.public(session,turn,self.server.image_jobs)
            req,profile=resolve_image_request(self.server.characters,self.server.image_jobs,decision)
            if decision["name"]=="edit_image":
                # Only the user's latest turn may provide additional reference
                # images. The model is NEVER allowed to choose filesystem paths.
                latest=next((m for m in reversed(payload["messages"])
                             if m.get("role")=="user"),{})
                content=latest.get("content")
                assets=[]
                if isinstance(content,list):
                    for item in content:
                        if not isinstance(item,dict) or item.get("type")!="image_url":
                            continue
                        url=(item.get("image_url") or {}).get("url")
                        if (not isinstance(url,str) or
                            not url.startswith(("data:image/png;base64,",
                                                "data:image/jpeg;base64,",
                                                "data:image/webp;base64,")) or
                            len(url)>7_200_000):
                            raise ValueError("无效的聊天参考图")
                        assets.append({"name":"user-chat-reference.png","data_url":url})
                        if len(assets)>7:
                            raise ValueError("最多允许七张额外参考图")
                if assets:
                    req["strata_reference_assets"]=assets
            # Edit may only use this session's latest successful image. The
            # ImageJobStore revalidates and resolves reference SERVER-side.
            token=self.store.decision_tool(session,turn,decision,req,profile,reasoning)
            if profile.get("require_approval",False):
                result=self.store.public(session,turn,self.server.image_jobs)
                result["approval_token"]=token  # one-time; never stored in plaintext
                result["model_name"]=profile["model_name"]
                return result
            self._dispatch(session,turn)
        except InvalidToolCall as exc:
            self.store.transition(session,turn,"deciding","tool_rejected",error=str(exc))
        except (ValueError,OSError,TimeoutError,http.client.HTTPException,TypeError,
                GPUUnavailable,StreamIncomplete) as exc:
            self.store.transition(session,turn,"deciding","decision_error",
                                  error=self._safe_error(exc))
        return self.store.public(session,turn,self.server.image_jobs)

    @staticmethod
    def _safe_error(exc):
        # Do not echo arbitrary provider/server response containing keys/paths.
        if isinstance(exc,GPUUnavailable): return "GPU 正忙于图像任务，未执行本次模型决策"
        if isinstance(exc,TimeoutError): return "模型决策超时；未创建图片任务"
        if isinstance(exc,InvalidToolCall): return str(exc)
        if isinstance(exc,chat_providers.ChatProviderError): return str(exc)[:160]
        if isinstance(exc,ValueError):
            msg=str(exc)
            if any(s in msg for s in ("全局","生图","图像","model","Model","Official","Worker")):
                return msg[:160]
        return "图像工具决策失败；未提交图片任务，请检查服务状态"

    def _dispatch(self,session,turn):
        row=self.store.get(session,turn)
        if row is None or row["state"]!="queued": return
        # No dispatch retry on ambiguous crash; GET only reconciles the
        # deterministic request_id with an already committed ImageJob.
        try:
            if not self.server.image_jobs or not self.server.image_jobs.worker_healthy():
                raise ValueError("独立 Image Worker 未就绪，未提交图像任务")
            req=json.loads(row["image_request_json"])
            decision=json.loads(row["decision_json"])
            runtime_mode=req.pop("_chat_runtime_mode","exclusive")
            job=self.server.image_jobs.chat_submit(
                session,turn,req,edit_previous=decision["name"]=="edit_image",
                runtime_mode=runtime_mode)
            self.store.transition(session,turn,"queued","running",job_id=job["id"])
            if self.store.public(session,turn,self.server.image_jobs).get("background"):
                self._start_announcement(session,turn)
        except (ValueError,OSError,TypeError) as exc:
            self.store.transition(session,turn,"queued","unavailable",
                                  error=self._safe_error(exc))

    @staticmethod
    def _reply_text(response):
        choice=(response.get("choices") or [{}])[0]
        message=choice.get("message") or {}
        text=message.get("content")
        if not isinstance(text,str) or not text.strip() or choice.get("finish_reason")=="tool_calls":
            raise ValueError("Follow-up model did not return plain text")
        return text.strip()

    def _session_context(self,session,request,limit=30):
        """Attach only messages settled in THIS same session after its user turn."""
        context=list(request["messages"][-45:])
        if request.get("_chat_provider"):return context
        try:
            web=self.server.conversations.get(session)["web_messages"]
            original_user=next((m for m in reversed(request["messages"])
                                if m.get("role")=="user"),{})
            body=original_user.get("content","")
            anchor=body if isinstance(body,str) else " ".join(
                str(x.get("text","")) for x in body if isinstance(x,dict) and x.get("type")=="text")
            index=max((i for i,m in enumerate(web) if m.get("role")=="user"
                       and str(m.get("text") or "")==anchor),default=-1)
            if index>=0:
                for message in web[index+1:][-limit:]:
                    role=message.get("role")
                    text=str(message.get("text") or "")[:2400]
                    if role in ("user","assistant") and text:
                        context.append({"role":role,"content":text})
        except (AttributeError,KeyError,LookupError,ValueError,TypeError,sqlite3.Error):
            LOG.debug("Extra session context unavailable for image follow-up")
        return context

    def _followup(self,session,turn,kind,event,max_tokens):
        """No tools, no reasoning and no image provider side effects."""
        row=self.store.get(session,turn)
        saved=json.loads(row["request_json"])
        original=json.loads(row["decision_json"])
        with self._session_decision_lock(session):
            context=self._session_context(session,saved)
            context.append({"role":"assistant","content":"",
                "tool_calls":[{"id":original["tool_call_id"],"type":"function",
                    "function":{"name":original["name"],"arguments":
                        json.dumps(original["arguments"],ensure_ascii=False)}}]})
            context.append({"role":"tool","tool_call_id":original["tool_call_id"],
                            "content":json.dumps(event,ensure_ascii=False)})
            guide=(
                "This image task has been ACCEPTED into the worker queue but has "
                "NOT completed yet. Given the existing conversation and the "
                "original user request, write a brief, natural acknowledgement "
                "in the assistant's normal persona, e.g. that you are adjusting "
                "the requested detail and will let them know when it is ready. "
                "Do not claim image edits are already finished. Do not use a "
                "fixed canned sentence. User can continue chatting while it runs. "
                "Do not call tools. Keep under 90 Chinese characters."
                if kind=="started" else FAILURE_INSTRUCTION)
            context.append({"role":"user","content":guide})
            response=self._chat_complete({"model":saved["model"],"stream":False,
                "messages":context[-85:],"tool_choice":"none","strata_mcp":False,
                "reasoning_effort":"none","reasoning_budget_tokens":0,
                "max_tokens":max_tokens},saved.get("_chat_provider"),timeout=180)
        return self._reply_text(response)

    def _start_announcement(self,session,turn):
        if not self.store.begin_start_reply(session,turn):
            return
        threading.Thread(target=self._announcement,args=(session,turn),
                         name="native-image-start-reply",daemon=True).start()

    def _announcement(self,session,turn):
        try:
            row=self.store.get(session,turn)
            decision=json.loads(row["decision_json"])
            event={"type":"image_job_started","job_kind":
                   "edit" if decision["name"]=="edit_image" else "generate",
                   "request_summary":str(decision["arguments"].get("instruction") or
                       decision["arguments"].get("prompt") or "")[:1000],
                   "status":"accepted_for_execution","can_continue_chat":True}
            reply=self._followup(session,turn,"started",event,160)
        except (ValueError,OSError,TimeoutError,http.client.HTTPException,
                TypeError,KeyError,GPUUnavailable) as exc:
            LOG.warning("image start reply unavailable type=%s",type(exc).__name__)
            reply="图片任务已提交，正在处理。"
        self.store.finish_start_reply(session,turn,reply)

    def _start_failure_reply(self,session,turn,job):
        raw=job.get("error") or job.get("phase") or ""
        category,detail=classify_error(raw)
        summary=detail[:200]
        if not self.store.transition(session,turn,("queued","running"),
                    "failure_running",job_id=job["id"],error=summary):
            return
        threading.Thread(target=self._failure_reply,
                         args=(session,turn,category,detail),
                         name="native-image-failure-reply",daemon=True).start()

    def _failure_reply(self,session,turn,category,detail):
        try:
            row=self.store.get(session,turn)
            decision=json.loads(row["decision_json"])
            event={"type":"image_job_failed",
                   "job_kind":"edit" if decision["name"]=="edit_image" else "generate",
                   "request_summary":str(decision["arguments"].get("instruction") or
                       decision["arguments"].get("prompt") or "")[:1000],
                   "error_category":category,
                   "provider_error_detail":detail,
                   "retry_automatic":False,"request_already_submitted":True}
            text=self._followup(session,turn,"failed",event,300)
        except (ValueError,OSError,TimeoutError,http.client.HTTPException,
                TypeError,KeyError,GPUUnavailable) as exc:
            LOG.warning("image failure reply unavailable type=%s",type(exc).__name__)
            text="这次图片没有生成成功，错误详情见上方任务卡片。我没有自动重新提交，要我帮你调整后再试吗？"
        self.store.transition(session,turn,"failure_running","image_failed",text=text[:1500])

    def approve(self,session,turn,token):
        self.store.accept_approval(session,turn,token)
        self._dispatch(session,turn)
        return self.store.public(session,turn,self.server.image_jobs)

    def cancel(self,session,turn):
        row=self.store.get(session,turn)
        if row is None: return None
        if row["state"]=="awaiting_approval":
            self.store.cancel_approval(session,turn)
        elif row["state"]=="deciding":
            self.store.transition(session,turn,"deciding","cancelled",
                text="已停止本次模型工具决策；不会创建图像任务")
        elif row["state"] in ("queued","running"):
            self.server.image_jobs.chat_cancel(session,turn)
            self.store.transition(session,turn,("queued","running"),"cancelled",
                                  text="已取消尚未认领的图像任务")
        else:
            raise ValueError("此状态不允许取消")
        return self.store.public(session,turn,self.server.image_jobs)

    def get(self,session,turn):
        self.reconcile(session,turn)
        return self.store.public(session,turn,self.server.image_jobs)

    def reconcile(self,session,turn):
        row=self.store.get(session,turn)
        if row is None or row["state"] not in ("queued","running","image_done"):
            return
        if row["state"]=="image_done":
            self._start_vision(session,turn)
            return
        job=self.store.job_for(row,self.server.image_jobs)
        if job is None:
            if time.time()-row["updated"]>35:
                self.store.transition(session,turn,("queued","running"),"unavailable",
                    error="未找到已提交的任务记录；为避免重复收费，不自动重试")
            return
        if job.get("state")=="success":
            self.store.transition(session,turn,("queued","running"),"image_done",
                                  job_id=job["id"])
            self._start_vision(session,turn)
        elif job.get("state") in ("failed","error","interrupted"):
            self._start_failure_reply(session,turn,job)
        else:
            self.store.transition(session,turn,"queued","running",job_id=job["id"])

    def _watch(self):
        while not self._stop.wait(2.0):
            try:
                for row in self.store.pending():
                    self.reconcile(row["session_id"],row["turn_id"])
            except (sqlite3.Error,OSError,ValueError,AttributeError,TypeError) as exc:
                LOG.warning("turn monitor issue type=%s",type(exc).__name__)

    def _start_vision(self,session,turn):
        row=self.store.get(session,turn)
        if row is None or row["state"]!="image_done":return
        if not self.store.transition(session,turn,"image_done","vision_running"):return
        with self._lock:
            if turn in self._active_visions:return
            self._active_visions.add(turn)
        threading.Thread(target=self._vision,args=(session,turn),
                         name="native-tool-vision",daemon=True).start()

    def _vision(self,session,turn):
        try:
            row=self.store.get(session,turn)
            job=self.store.job_for(row,self.server.image_jobs)
            result=job.get("result") if job else {}
            filename=result.get("image_file") if isinstance(result,dict) else None
            if not isinstance(filename,str) or not IMAGE_NAME.fullmatch(filename):
                raise ValueError("No generated image exists for this turn")
            raw=gallery._file(self.server.image_jobs,filename[:-4]).read_bytes()
            if len(raw)>25*1024*1024: raise ValueError("Image too large for vision")
            with Image.open(io.BytesIO(raw)) as picture:
                picture=picture.convert("RGB")
                picture.thumbnail((768,768))
                out=io.BytesIO()
                picture.save(out,format="JPEG",quality=78)
            image="data:image/jpeg;base64,"+base64.b64encode(out.getvalue()).decode("ascii")
            saved=json.loads(row["request_json"])
            original=json.loads(row["decision_json"])
            ref=saved.get("_chat_provider")
            if ref and not chat_providers.resolve(self.store.path.parent,ref)["vision"]:
                self.store.transition(session,turn,"vision_running","vision_done",text="图片已生成。当前聊天模型未启用视觉理解，请直接查看图片。")
                return
            context=list(saved["messages"][-40:])
            context.append({"role":"assistant","content":"",
                "tool_calls":[{"id":original["tool_call_id"],"type":"function",
                    "function":{"name":original["name"],"arguments":
                        json.dumps(original["arguments"],ensure_ascii=False)}}]})
            context.append({"role":"tool","tool_call_id":original["tool_call_id"],
                            "content":"Image generation succeeded. The attached image is the result."})
            # Wait for any already-streaming answer in this session first.
            # Then load the freshest settled messages before visual feedback.
            with self._session_decision_lock(session):
                try:
                    web=[] if ref else self.server.conversations.get(session)["web_messages"]
                    original_user=next((m for m in reversed(saved["messages"])
                                        if m.get("role")=="user"),{})
                    body=original_user.get("content","")
                    anchor=(body if isinstance(body,str) else
                            " ".join(str(x.get("text","")) for x in body
                                     if isinstance(x,dict) and x.get("type")=="text"))
                    anchor_index=max((i for i,m in enumerate(web) if m.get("role")=="user"
                                      and str(m.get("text") or "")==anchor),default=-1)
                    if anchor_index>=0:
                        for webmsg in web[anchor_index+1:][-30:]:
                            role=webmsg.get("role")
                            text=str(webmsg.get("text") or "")[:2500]
                            if role in ("user","assistant") and text:
                                context.append({"role":role,"content":text})
                except (AttributeError,KeyError,LookupError,ValueError,TypeError,sqlite3.Error):
                    LOG.debug("No additional settled session messages available for vision tail")
                context.append({"role":"user","content":[
                    {"type":"text","text":(
                        "The image job you started for the user has now FINISHED. This is the actual "
                        "result, not a new user request. Using the user's original image request and "
                        "the most recent conversation, write a warm, natural completion message "
                        "addressed directly to the user (in the user's language). In Chinese start "
                        "naturally like '画好了，你看看！' then describe one or two specific details "
                        "actually visible in this image and how they relate to the requested subject "
                        "or style. If the user has since discussed changes, acknowledge that context "
                        "without falsely claiming those changes were applied. Avoid generic flattery, "
                        "invisible details, and new tool calls. Keep it brief, up to 150 Chinese chars.")},
                    {"type":"image_url","image_url":{"url":image}}]})
                response=self._chat_complete({"model":saved["model"],"stream":False,
                    "messages":context[-85:],"tool_choice":"none","strata_mcp":False,
                    "reasoning_effort":"none","reasoning_budget_tokens":0,
                    "max_tokens":256},ref,timeout=180)
            choice=(response.get("choices") or [{}])[0]
            text=(choice.get("message") or {}).get("content")
            if not isinstance(text,str) or not text.strip() or choice.get("finish_reason")=="tool_calls":
                raise ValueError("No valid visual reply")
            self.store.transition(session,turn,"vision_running","vision_done",text=text[:1200])
        except (ValueError,OSError,TimeoutError,http.client.HTTPException,TypeError,KeyError) as exc:
            LOG.warning("vision tail failed type=%s",type(exc).__name__)
            self.store.transition(session,turn,"vision_running","vision_failed",
                error="图片已成功；本次视觉尾部未完成",text="图片已生成，但视觉理解暂未完成。")
        finally:
            with self._lock: self._active_visions.discard(turn)
