import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {readFileSync} from "node:fs";
import vm from "node:vm";
const require=createRequire(import.meta.url);
const status=require("../native-header-status.js");
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const local=readFileSync(new URL("../local-model-settings.js",import.meta.url),"utf8");

const idle={live:{state:"idle",queued:0}};
const writing={live:{state:"generating",queued:0,tok_s:25.6}};
const loaded={component:"mikuchin-gateway",official_polystrata_reachable:true,
    official_model_loaded:true,native_gpu:{busy:false,phase:"idle"},
    native_image_jobs:{running:0,phase:""}};
test("top pill resolves idle vs unloaded in one stable decision",()=>{
 const health={...loaded,official_model_loaded:false};
 assert.equal(status.resolve({metrics:idle,health}).text,"模型已空闲卸载");
 assert.equal(status.resolve({metrics:idle,health}).text,
    status.resolve({metrics:idle,health}).text);
});
test("text inference wins over concurrent image; image is secondary",()=>{
 const health={...loaded,native_image_jobs:{running:2,phase:"调用图像 API"}};
 const got=status.resolve({metrics:writing,health});
 assert.match(got.text,/25\.6 tok\/s/);
 assert.equal(got.imageCount,2);
});
test("exclusive unload and restore take precedence over idle metrics",()=>{
 for(const [phase,word] of [["unloading","卸载"],["restoring","恢复"],
                           ["upscaling","超分"]]){
   const health={...loaded,native_gpu:{busy:true,phase}};
   assert.match(status.resolve({metrics:idle,health}).text,new RegExp(word));
 }
});
test("error and model lifecycle states remain separate",()=>{
 assert.equal(status.resolve({metrics:null,health:{...loaded,
   official_polystrata_reachable:false}}).text,"推理引擎暂不可用");
 assert.equal(status.resolve({metrics:null,health:null,networkFailed:true}).text,
   "服务无法连接");
 assert.equal(status.resolve({unauthorized:true}).text,"需要 API Key");
});
test("header has one pill writer and versioned secondary task label",()=>{
 const writes=Array.from(app.matchAll(/setPill\(/g));
 // One use is the function declaration; one use is in paintHeaderStatus.
 assert.equal(writes.length,2);
 assert.match(html,/id="pill-image"/);
 assert.match(html,/native-header-status\.js/);
});
test("tool clock starts at provider inference, not queue timestamp",()=>{
 assert.match(app,/data-native-tool-clock-start/);
 const text=app.slice(app.indexOf("function renderNativeToolClocks("),
   app.indexOf("setInterval(renderNativeToolClocks,1000);"));
 const labels=[
   {dataset:{nativeToolClockStart:"100"},textContent:""},
   {dataset:{nativeToolClockStart:"100",nativeToolClockEnd:"190"},textContent:""}
 ];
 const ctx={document:{querySelectorAll:()=>labels},Number,Date,Math,String};
 vm.runInNewContext(text+"\nthis.tick=renderNativeToolClocks",ctx);
 ctx.tick(135000);
 assert.equal(labels[0].textContent,"已运行 00:35");
 assert.equal(labels[1].textContent,"耗时 01:30");
 assert.match(html,/local-model-settings\.js/);
});
test("local import UI is file registration, never executable upload",()=>{
 assert.match(html,/id="mk-local-import-open"/);
 assert.match(html,/id="mk-local-import-form"/);
 assert.match(html,/id="mk-local-model-list"/);
 assert.match(local,/local-image-models/);
 assert.match(local,/localHost/);
 assert.doesNotMatch(html,/id="mk-local-exe"/);
});
