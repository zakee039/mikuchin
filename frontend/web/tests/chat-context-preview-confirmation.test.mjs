import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import {readFileSync} from "node:fs";
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const service=readFileSync(new URL("../image-api-settings.js",import.meta.url),"utf8");
const viewer=readFileSync(new URL("../chat-image-viewer.js",import.meta.url),"utf8");
const viewerCss=readFileSync(new URL("../chat-image-viewer.css",import.meta.url),"utf8");

test("stateless and ordinary modes both preserve this session's complete history",()=>{
 const a=app.slice(app.indexOf("async function streamInto("),app.indexOf("// ------------------------------------------------------------------ tools"));
 const b=app.slice(app.indexOf("async function submitModelToolTurn("),app.indexOf("function confirmNativePaidImage("));
 assert.match(a,/const assembledMessages=history/);
 assert.match(b,/const context=history/);
 assert.match(b,/const roleSystem=stateless \? null/);
 assert.doesNotMatch(a,/filter\(x=>x\.role==="user"\)\.at\(-1\)/);
 assert.doesNotMatch(b,/history\.filter\(x => x\.role === "user"\)\.at\(-1\)/);
});
test("Miku follow-up retains prior user subject plus actual image tool prompt",()=>{
 const part=app.slice(app.indexOf("function apiMessages()"),app.indexOf("function setBusy("));
 const messages=[
   {role:"user",text:"生成一张初音未来的真人图"},
   {role:"assistant",text:"这张初音未来真人图已经生成",reasoning:"",
    tools:[{id:"call_abc",name:"generate_image",round:1,at:0,state:"done",
      arguments:{prompt:"Hatsune Miku, realistic turquoise twin-tails"},
      result:"Image generation succeeded. Image is available in conversation."}]},
   {role:"user",text:"再生成一张二次元的"},
   {role:"assistant",text:"",tools:null}
 ];
 const context={messages,busy:{msg:messages[3]},userText:m=>m.text};
 vm.runInNewContext(part,context);
 const sent=context.apiMessages();
 assert.deepEqual(Array.from(sent.map(m=>m.role)),["user","assistant","tool","assistant","user"]);
 assert.match(sent[0].content,/初音未来/);
 assert.match(sent[1].tool_calls[0].function.arguments,/Hatsune Miku/);
 assert.equal(sent.at(-1).content,"再生成一张二次元的");
});
test("online API form has OFF-by-default chat-only confirmation",()=>{
 assert.match(html,/id="mk-api-chat-confirm"/);
 assert.match(html,/仅在聊天中模型调用此 API 生图时生效/);
 assert.match(service,/chat_confirm_each_call: get\("mk-api-chat-confirm"\)\.checked/);
 assert.match(service,/item\?\.chat_confirm_each_call === true/);
});
test("chat preview offers download and close only, no gallery operations",()=>{
 const section=html.slice(html.indexOf('id="chat-image-viewer"'),
                          html.indexOf('id="toasts"'));
 const actions=Array.from(section.matchAll(/<button\b/g));
 assert.equal(actions.length,2);
 assert.match(section,/id="chat-image-viewer-download"/);
 assert.match(section,/id="chat-image-viewer-close"/);
 assert.doesNotMatch(section,/删除|编辑|前一张|后一张|放大|超分/);
 assert.match(viewer,/MikuchinSecureImages/);
 assert.match(viewer,/secure\.load\(img,path\)/);
 assert.match(viewer,/secure\.prefetch\(path\)/);
 assert.match(viewer,/URL\.revokeObjectURL/);
 assert.match(viewerCss,/chat-image-viewer\[hidden\]/);
 const render=app.slice(app.indexOf("function answerHtml("),app.indexOf("function onTool("));
 assert.match(render,/data-native-image-preview/);
 assert.doesNotMatch(render,/data-native-image-download/);
});
