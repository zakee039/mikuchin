import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const handler=app.match(/\$\("input"\)\.addEventListener\("keydown", \(e\) => \{[\s\S]*?\n\}\);/)[0];
function simulate(overrides={}){
  let listener, sent=0, prevented=0;
  vm.runInNewContext(handler,{$:()=>({addEventListener:(kind,fn)=>{assert.equal(kind,"keydown");listener=fn;}}),send:()=>sent++});
  listener({key:"Enter",shiftKey:false,isComposing:false,keyCode:13,repeat:false,preventDefault:()=>prevented++,...overrides});
  return {sent,prevented};
}
test("plain Enter uses native multiline editing on desktop and mobile",()=>assert.deepEqual(simulate(),{sent:0,prevented:0}));
test("Shift+Enter submits exactly once",()=>assert.deepEqual(simulate({shiftKey:true}),{sent:1,prevented:1}));
test("IME composition and legacy keyCode 229 never send",()=>{
  assert.deepEqual(simulate({shiftKey:true,isComposing:true}),{sent:0,prevented:0});
  assert.deepEqual(simulate({shiftKey:true,keyCode:229}),{sent:0,prevented:0});
});
test("holding Shift+Enter does not send again or insert unwanted newline",()=>assert.deepEqual(simulate({shiftKey:true,repeat:true}),{sent:0,prevented:1}));
test("unrelated keys preserve native behavior",()=>assert.deepEqual(simulate({key:"a",shiftKey:true}),{sent:0,prevented:0}));
test("mobile keyboard hint is newline and visible send button still submits",()=>{
  assert.match(html,/<textarea id="input"[^>]*enterkeyhint="enter"/);
  assert.match(html,/<button type="submit"[^>]*id="send-btn"/);
  assert.match(app,/\$\("composer"\)\.onsubmit = \(e\) => \{ e\.preventDefault\(\); send\(\); \};/);
  assert.ok(app.includes("Shift+Enter: send"));
});
