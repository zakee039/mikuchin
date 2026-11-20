import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";

const require=createRequire(import.meta.url);
const router=require("../chat-image-intent.js");
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");

test("strict JSON router parsing only accepts explicit action allowlist",()=>{
  assert.equal(router.parse('{"action":"generate"}'),"generate");
  assert.equal(router.parse('{"action":"edit"}',true),"edit");
  assert.equal(router.parse('{"action":"edit"}',false),"text");
  assert.equal(router.parse('```json\n{"action":"generate"}\n```'),"generate");
  for(const input of ["generate", "The answer is generate",
    '{"action":"pay_now"}',"{\"action\":null}", '{"action":"generate"', "[]", "null", ""]) {
    assert.equal(router.parse(input),"text",input);
  }
});

test("local classifier never submits paid tasks or enables unsafe tools",async()=>{
  const oldFetch=global.fetch;
  const captured=[];
  try {
    global.fetch=async (url,options)=>{
      captured.push({url,options,body:JSON.parse(options.body)});
      return {ok:true,json:async()=>({choices:[{message:{content:'{"action":"generate"}'}}]})};
    };
    const result=await router.classify({text:"画一个蓝色的星星",model:"mock",
      hasPreviousImage:false,headers:{Authorization:"Bearer disposable"}});
    assert.equal(result,"generate");
    assert.equal(captured.length,1);
    assert.equal(captured[0].url,"v1/chat/completions");
    assert.equal(captured[0].body.messages[0].role,"system");
    assert.match(captured[0].body.messages[0].content,/MIKUCHIN_IMAGE_ROUTER_V1/);
    assert.equal(captured[0].body.strata_image_tool,false);
    assert.equal(captured[0].body.strata_mcp,false);
    assert.equal(captured[0].body.reasoning_effort,"none");
    assert.equal(captured[0].body.max_tokens,80);
    assert.equal(captured[0].body.stream,false);
    assert.equal(captured[0].options.headers.Authorization,"Bearer disposable");
    assert.equal(router.parse('{"action":"edit"}'),"text");
  } finally {global.fetch=oldFetch;}
});

test("auto image mode is opt-in and confirmation remains mandatory",()=>{
  assert.match(app,/store\.get\("auto-image-route",false\) === true/);
  assert.match(app,/autoImageEnabled\(\) && health\.chat_image_jobs/);
  assert.match(app,/MikuchinImageIntent\.classify/);
  assert.match(app,/decision==="generate" \|\| decision==="edit"/);
  assert.match(app,/await sendNativeChatImage\(\{prompt:text,editPrevious:decision==="edit"\}\)/);
  assert.match(app,/const accepted=await confirmNativeChatImage\(cfg\)/);
  assert.match(app,/if \(!accepted\) return/);
  assert.match(html,/id="chat-auto-btn"/);
  assert.match(html,/aria-checked="false"/);
  assert.match(html,/chat-image-intent\.js\?v=/);
  assert.ok(html.indexOf("web/chat-image-intent.js") < html.indexOf("web/app.js"));
});

test("edit uses server-owned source and cannot switch sessions during routing",()=>{
  assert.match(app,/edit_previous:editPrevious/);
  assert.match(app,/修改本会话上一张图片/);
  assert.match(app,/sessionId!==startingSession/);
  assert.match(app,/!attachments\.length && window\.MikuchinImageIntent/);
  assert.match(app,/intentRouting=true/);
  assert.match(app,/intentRouting=false/);
  assert.match(app,/intentController=controller/);
  assert.match(app,/跳过识别/);
  assert.match(app,/if \(intentRouting && intentController\) intentController\.abort\(\)/);
});
