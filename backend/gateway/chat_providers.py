"""Server-owned OpenAI-compatible chat profiles and non-replaying adapter."""
from __future__ import annotations
import base64
import json
import os
import re
import secrets
import threading
from pathlib import Path
from urllib.parse import urlsplit
import requests
try:
    from .chat_streaming import ToolStreamAssembler, StreamIncomplete
except ImportError:
    from chat_streaming import ToolStreamAssembler, StreamIncomplete

_LOCK=threading.RLock()
PROFILE=re.compile(r"chat-api-[a-f0-9]{16}\Z")
MAX_RESPONSE=4*1024*1024

class ChatProviderError(ValueError):
    pass


def _path(root): return Path(root)/"chat-api-services.json"

def _read(root):
    p=_path(root)
    return json.loads(p.read_text(encoding="utf-8"))["services"] if p.exists() else []

def _write(root, entries):
    p=_path(root);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name("."+p.name+"."+secrets.token_hex(6)+".tmp")
    try:
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump({"services":entries},f,ensure_ascii=False,indent=2)
        os.replace(tmp,p)
    finally:tmp.unlink(missing_ok=True)

def public(entry):
    fields=("id","name","model","base_url","proxy","proxy_url","stream","vision","tools","reasoning","context_tokens","timeout_seconds","max_tokens","revision")
    return {k:entry[k] for k in fields if k in entry} | {"has_key":bool(entry.get("protected_key") or entry.get("api_key"))}

def listing(root):
    with _LOCK:return [public(x) for x in _read(root)]

def get(root, ident):
    with _LOCK:return next((dict(e) for e in _read(root) if e["id"]==ident),None)

def _url(value, proxy=False):
    if not isinstance(value,str) or not value or len(value)>2048:raise ChatProviderError("无效的 API 地址")
    val=value.strip().rstrip("/");p=urlsplit(val)
    schemes=("http","https","socks5","socks5h") if proxy else ("http","https")
    if p.scheme not in schemes or not p.hostname or p.username or p.password or p.query or p.fragment:raise ChatProviderError("无效的 API 地址")
    try:port=p.port
    except ValueError:raise ChatProviderError("无效的 API 端口") from None
    if proxy and p.path not in ("", "/"):raise ChatProviderError("代理地址不应包含路径")
    if not proxy and p.path.endswith("/chat/completions"):raise ChatProviderError("Base URL 不应包含 /chat/completions")
    if not proxy and p.scheme=="http" and p.hostname not in ("127.0.0.1","localhost","::1"):raise ChatProviderError("在线聊天服务必须使用 HTTPS；HTTP 仅允许本机服务")
    return val

def _protect(value, binding, decrypt=False):
    # Windows DPAPI protects newly configured provider credentials at rest.
    # Bind the secret to its original endpoint/route, preventing config-only
    # edits from redirecting an existing credential to another origin.
    if os.name!="nt":return value
    import ctypes as c
    from ctypes import wintypes as w
    class Blob(c.Structure):_fields_=[("cbData",w.DWORD),("pbData",c.POINTER(c.c_ubyte))]
    def blob(raw):
        buf=(c.c_ubyte*len(raw)).from_buffer_copy(raw)
        return Blob(len(raw),c.cast(buf,c.POINTER(c.c_ubyte))),buf
    raw=base64.b64decode(value,validate=True) if decrypt else value.encode("utf-8")
    source,hold=blob(raw);entropy,hold2=blob(binding.encode("utf-8"));dest=Blob()
    crypt=c.windll.crypt32;kernel=c.windll.kernel32
    kernel.LocalFree.argtypes=[c.c_void_p];kernel.LocalFree.restype=c.c_void_p
    fn=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes=[c.POINTER(Blob),c.c_void_p,c.POINTER(Blob),c.c_void_p,c.c_void_p,w.DWORD,c.POINTER(Blob)]
    fn.restype=w.BOOL
    if not fn(c.byref(source),None,c.byref(entropy),None,None,1,c.byref(dest)):raise ChatProviderError("聊天 API 凭据无法在当前 Windows 用户下使用，请重新配置")
    try:
        out=c.string_at(dest.pbData,dest.cbData)
        return out.decode("utf-8") if decrypt else base64.b64encode(out).decode("ascii")
    finally:kernel.LocalFree(c.cast(dest.pbData,c.c_void_p))

def _binding(entry):return json.dumps([entry["id"],entry["base_url"],entry["proxy_url"]],ensure_ascii=False,separators=(",",":"))

def _key(entry):
    if os.name=="nt":return _protect(entry.get("protected_key",""),_binding(entry),True) if entry.get("protected_key") else ""
    return entry.get("api_key","")

def save(root, data):
    if not isinstance(data,dict):raise ChatProviderError("无效的聊天服务")
    with _LOCK:
        entries=_read(root);ident=data.get("id") or "chat-api-"+secrets.token_hex(8)
        if not isinstance(ident,str) or not PROFILE.fullmatch(ident):raise ChatProviderError("无效的聊天服务 ID")
        prev=next((e for e in entries if e["id"]==ident),None)
        if not prev and len(entries)>=30:raise ChatProviderError("最多 30 个聊天 API 服务")
        def string(k,limit):
            value=data.get(k,"")
            if not isinstance(value,str) or not 0<len(value.strip())<=limit or any(c in value for c in "\r\n"):raise ChatProviderError("无效的 "+k)
            return value.strip()
        def flag(k,default=False):
            value=data.get(k,default)
            if type(value) is not bool:raise ChatProviderError("无效的 "+k)
            return value
        def integer(k,default,lo,hi):
            value=data.get(k,default)
            if type(value) is not int or not lo<=value<=hi:raise ChatProviderError("无效的 "+k)
            return value
        proxy=flag("proxy")
        entry={"id":ident,"name":string("name",80),"model":string("model",200),"base_url":_url(data.get("base_url")),"proxy":proxy,"proxy_url":_url(data.get("proxy_url"),True) if proxy else "","stream":flag("stream",True),"vision":flag("vision"),"tools":flag("tools"),"reasoning":flag("reasoning"),"timeout_seconds":integer("timeout_seconds",240,30,1200),"max_tokens":None if data.get("max_tokens") is None else integer("max_tokens",None,128,65536),"revision":secrets.token_hex(12)}
        key=data.get("api_key","")
        if not isinstance(key,str) or len(key)>4096 or any(c in key for c in "\r\n"):raise ChatProviderError("无效的 API Key")
        if not key and prev:
            if _binding(entry)!=_binding(prev):raise ChatProviderError("连接地址或代理改变，请重新输入 API Key")
            for k in ("api_key","protected_key"):
                if k in prev:entry[k]=prev[k]
        elif key:
            if os.name=="nt":entry["protected_key"]=_protect(key,_binding(entry))
            else:entry["api_key"]=key
        if not entry.get("api_key") and not entry.get("protected_key"):raise ChatProviderError("请填写 API Key")
        _write(root,[e for e in entries if e["id"]!=ident]+[entry]);return public(entry)

def discover(root, connection):
    """Read the provider catalog only. No completion or saved configuration changes."""
    if not isinstance(connection,dict):raise ChatProviderError("无效的连接配置")
    ident=connection.get("id")
    existing=None
    if ident is not None:
        if not isinstance(ident,str) or not PROFILE.fullmatch(ident):raise ChatProviderError("无效的聊天服务 ID")
        existing=get(root,ident)
        if not existing:raise ChatProviderError("聊天服务不存在")
    proxy=connection.get("proxy",False)
    if type(proxy) is not bool:raise ChatProviderError("无效的代理配置")
    route={"id":ident,"base_url":_url(connection.get("base_url")),"proxy_url":_url(connection.get("proxy_url"),True) if proxy else ""}
    key=connection.get("api_key","")
    if not isinstance(key,str) or len(key)>4096 or any(c in key for c in "\r\n"):raise ChatProviderError("无效的 API Key")
    if not key and existing:
        if _binding(route)!=_binding(existing):raise ChatProviderError("连接地址或代理改变，请重新输入 API Key")
        key=_key(existing)
    if not key:raise ChatProviderError("请填写 API Key")
    try:
        with requests.Session() as sess:
            sess.trust_env=False
            if proxy:sess.proxies={"http":route["proxy_url"],"https":route["proxy_url"]}
            with sess.get(route["base_url"]+"/models",headers={"Authorization":"Bearer "+key,"Accept":"application/json"},timeout=(8,20),stream=True,allow_redirects=False) as resp:
                if resp.status_code!=200:raise ChatProviderError("获取模型失败 (HTTP "+str(resp.status_code)+")")
                raw=bytearray()
                for chunk in resp.iter_content(65536):
                    raw.extend(chunk)
                    if len(raw)>2*1024*1024:raise ChatProviderError("模型列表超过 2 MB")
                data=json.loads(raw)
    except requests.RequestException:raise ChatProviderError("获取模型时网络异常或超时") from None
    except (json.JSONDecodeError,UnicodeError):raise ChatProviderError("服务商未返回有效模型列表 JSON") from None
    items=data.get("data",data.get("models")) if isinstance(data,dict) else None
    if not isinstance(items,list):raise ChatProviderError("服务商未返回兼容的模型列表")
    result=[];seen=set()
    for item in items:
        entry=item if isinstance(item,dict) else {"id":item}
        model=entry.get("id") or entry.get("model")
        if not isinstance(model,str) or not 0<len(model)<=200 or model in seen or any(c in model for c in "\r\n"):continue
        seen.add(model)
        # The standard catalog often has only IDs. Use only explicit boolean metadata.
        caps={}
        for source in (entry,entry.get("capabilities")):
            if not isinstance(source,dict):continue
            for dest,aliases in (("stream",("streaming","supports_streaming")),("vision",("vision","supports_vision")),("tools",("tools","tool_calling","supports_tools","supports_tool_calling")),("reasoning",("reasoning","supports_reasoning"))):
                for alias in aliases:
                    if type(source.get(alias)) is bool:caps[dest]=source[alias];break
        result.append({"id":model,"capabilities":caps})
        if len(result)>=2000:break
    return {"models":result}

def delete(root,ident):
    with _LOCK:
        entries=_read(root);new=[e for e in entries if e["id"]!=ident]
        if len(entries)==len(new):raise ChatProviderError("聊天服务不存在")
        _write(root,new)

def resolve(root, ref):
    if not isinstance(ref,dict) or not isinstance(ref.get("id"),str):raise ChatProviderError("聊天服务未选择")
    entry=get(root,ref["id"])
    if not entry or entry["revision"]!=ref.get("revision"):raise ChatProviderError("聊天模型配置已修改或删除；未切换其他服务，请重新选择")
    return entry

def _wire_payload(entry,payload):
    # No local engine fields or credentials from the browser reach providers.
    messages=payload.get("messages") or []
    latest_user=max((i for i,m in enumerate(messages) if m.get("role")=="user"),default=-1)
    clean=[]
    for i,m in enumerate(messages):
        row={k:v for k,v in m.items() if k in ("role","content","tool_calls","tool_call_id","name")}
        if not entry["vision"] and isinstance(row.get("content"),list):
            parts=row["content"]
            has_image=any(isinstance(part,dict) and part.get("type")=="image_url" for part in parts)
            if has_image and i==latest_user:raise ChatProviderError("当前聊天 API 不支持本次图片输入，请选择视觉模型")
            if has_image:
                row["content"]="\n".join(str(part.get("text") or "") if part.get("type")=="text" else "[Historical image not sent: text-only model]" for part in parts if isinstance(part,dict))
        if row.get("role")=="developer":row["role"]="system"
        # Plain text-only models cannot accept historical tool protocol.
        if not entry["tools"]:
            if row.get("role")=="tool":row={"role":"assistant","content":"[Previous tool result] "+str(row.get("content") or "")}
            else:row.pop("tool_calls",None)
        clean.append(row)
    out={"model":entry["model"],"messages":clean}
    limits=[v for v in (entry.get("max_tokens"),payload.get("max_tokens")) if type(v) is int and v>0]
    if limits:out["max_tokens"]=min(limits)
    for k in ("temperature","top_p","seed"):
        if k in payload:out[k]=payload[k]
    if entry["reasoning"] and payload.get("reasoning_effort") in ("low","medium","high"):out["reasoning_effort"]=payload["reasoning_effort"]
    if entry["tools"] and payload.get("tools"):
        out["tools"]=payload["tools"];out["tool_choice"]=payload.get("tool_choice","auto")
    return out

def complete(root,ref,payload,monitor,on_delta=None):
    entry=resolve(root,ref);wire=_wire_payload(entry,payload)
    stream=bool(on_delta is not None and entry["stream"]);wire["stream"]=stream
    raw=json.dumps(wire,ensure_ascii=False,allow_nan=False).encode("utf-8")
    if len(raw)>7*1024*1024:raise ChatProviderError("在线聊天请求过大")
    ticket=monitor.begin("chat");status=502;received=0;ok=False
    try:
        with requests.Session() as sess:
            sess.trust_env=False
            if entry["proxy"]:sess.proxies={"http":entry["proxy_url"],"https":entry["proxy_url"]}
            with sess.post(entry["base_url"]+"/chat/completions",data=raw,headers={"Authorization":"Bearer "+_key(entry),"Content-Type":"application/json","Accept":"text/event-stream" if stream else "application/json"},timeout=(30,entry["timeout_seconds"]),stream=True,allow_redirects=False) as resp:
                status=resp.status_code
                if status!=200:raise ChatProviderError("聊天 API 请求失败 (HTTP "+str(status)+")；未自动重试")
                if stream and "text/event-stream" in resp.headers.get("Content-Type","").lower():
                    result=ToolStreamAssembler();deliver=True
                    for line in resp.iter_lines(chunk_size=1024):
                        received+=len(line)+1
                        if received>MAX_RESPONSE:raise ChatProviderError("聊天 API 响应过大")
                        delta=result.consume(line)
                        if delta and deliver:
                            try:on_delta(delta)
                            except OSError:deliver=False
                        if result.done:break
                    obj=result.complete()
                else:
                    chunks=[]
                    for chunk in resp.iter_content(65536):
                        received+=len(chunk)
                        if received>MAX_RESPONSE:raise ChatProviderError("聊天 API 响应过大")
                        chunks.append(chunk)
                    obj=json.loads(b"".join(chunks))
                if not isinstance(obj,dict) or "error" in obj:raise ChatProviderError("聊天 API 返回无效结果")
                choices=obj.get("choices")
                if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict) or not isinstance(choices[0].get("message"),dict):raise ChatProviderError("聊天 API 未返回有效回复")
                message=choices[0]["message"]
                if not wire.get("tools") and message.get("tool_calls"):raise ChatProviderError("当前请求不允许工具调用")
                ok=True;return obj
    except requests.Timeout:raise ChatProviderError("聊天 API 响应超时；未自动重试") from None
    except requests.RequestException:raise ChatProviderError("聊天 API 网络异常；未自动重试") from None
    except (json.JSONDecodeError,UnicodeError,StreamIncomplete):raise ChatProviderError("聊天 API 响应不完整或协议不兼容；未自动重试") from None
    finally:monitor.finish(ticket,status=status,response_bytes=received,outcome="completed" if ok else "upstream_error")
