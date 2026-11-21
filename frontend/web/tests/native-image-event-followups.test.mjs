import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";
const require=createRequire(import.meta.url);
const client=require("../native-tool-client.js");
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const chars=readFileSync(new URL("../characters.js",import.meta.url),"utf8");
const css=readFileSync(new URL("../app.css",import.meta.url),"utf8");
const session="a".repeat(32),turn="b".repeat(32);
const make=()=>({role:"assistant",text:"",reasoning:"",native_turn_id:turn,time:Date.now()});
const response=(state,extra={})=>({
 session_id:session,turn_id:turn,state,online:true,background:true,
 tool:{name:"edit_image",tool_call_id:"call_miku",
       arguments:{instruction:"把衣服调整成淡蓝色"}},...extra});

test("API image model hides full runtime field and makes model selector full-width",()=>{
 assert.match(html,/id="global-chat-image-runtime-field"/);
 assert.match(chars,/runtime-field"\)\.hidden=apiMode/);
 assert.match(chars,/chat-image-model-mode-row--api",apiMode/);
 assert.match(css,/#global-chat-image-runtime-field\[hidden\]\{display:none\}/);
 assert.match(css,/chat-image-model-mode-row--api\{grid-template-columns:minmax\(0,1fr\)/);
});
test("real model start acknowledgement persists and is not replaced by polling",()=>{
 const m=make();
 client.apply(m,response("running",{start_state:"done",start_text:
   "好，我把你提到的初音未来衣服调成淡蓝色重新生成，稍后告诉你结果。"}));
 assert.match(m.text,/初音未来/);
 assert.equal(m.reasoning,"");
 client.apply(m,response("vision_running",{start_state:"done",start_text:m.text}));
 assert.match(m.text,/淡蓝色/);
});
test("failed task preserves error card and delivers one separate LLM reply after ongoing chat",()=>{
 const m=make();
 client.apply(m,response("running",{start_text:"我按照你的要求重新生成啦。"}));
 client.apply(m,response("failure_running",{error:"content_policy_violation"}));
 assert.equal(m.tools[0].state,"error");
 assert.equal(client.unfinished(m),true);
 client.apply(m,response("image_failed",{error:"content_policy_violation",
   text:"这次服务返回内容审核拦截。我建议保持日常服饰描述，需要我重新提交吗？"}));
 assert.equal(m.native_completion_type,"failed");
 assert.equal(m.native_completion_ready,true);
 assert.match(m.tools[0].result,/content_policy_violation/);
 const source=app.slice(app.indexOf("function deliverNativeBackgroundCompletions()"),
                         app.indexOf("async function submitModelToolTurn("));
 const ordinary={role:"assistant",text:"配色建议稍微偏冷",time:Date.now()};
 const context={messages:[m,ordinary],busy:{msg:ordinary},sessionId:session,
   saveChat:()=>{context.saves++},renderChat:()=>{},scrollDown:()=>{},saves:0};
 vm.runInNewContext(source+"\nthis.finish=deliverNativeBackgroundCompletions;",context);
 context.finish();
 assert.equal(context.messages.length,2);
 context.busy=null;
 context.finish();
 assert.equal(context.messages.length,3);
 assert.equal(context.messages[2].native_completion_of,turn);
 assert.equal(context.messages[2].tools,null);
 assert.match(context.messages[2].text,/审核拦截/);
 assert.equal(context.messages[0].tools[0].state,"error");
 context.finish();
 assert.equal(context.messages.length,3);
 assert.equal(context.saves,1);
});
test("the backend's start reply must re-render on a read-only poll",()=>{
 assert.match(app,/turn\.start_text,turn\.start_state/);
 assert.match(app,/deliverNativeBackgroundCompletions\(\)/);
});
