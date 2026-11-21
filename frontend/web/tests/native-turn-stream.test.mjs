import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {test} from "node:test";
import {readFileSync} from "node:fs";
const require=createRequire(import.meta.url);
const {Decoder}=require("../native-turn-stream.js");
const client=require("../native-tool-client.js");
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const sessions=readFileSync(new URL("../sessions.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");

test("SSE safely handles split UTF-8-style chunks, thought and final completion",()=>{
 const events=[],p=new Decoder(e=>events.push(e));
 const text='data: {"type":"delta","reasoning":"先思考"}\n\n';
 p.push(text.slice(0,19));p.push(text.slice(19));
 p.push('data: {"type":"delta","text":"正在回答"}\r\n');
 p.push('data: {"type":"done","turn":{"state":"text_done","text":"正在回答"}}\n\n');
 p.finish();
 assert.deepEqual(events.map(e=>e.type),["delta","delta","done"]);
 assert.equal(events[0].reasoning,"先思考");
});
test("SSE missing final decision never claims success",()=>{
 const p=new Decoder(()=>{});
 p.push('data: {"type":"delta","text":"partial"}\n');
 assert.throws(()=>p.finish(),/without a confirmed result/);
});
test("SSE malformed JSON cannot be used as tool command",()=>{
 const p=new Decoder(()=>{});
 assert.throws(()=>p.push('data: {bad json}\n'),/Invalid Native tool stream/);
});
test("Local image task names represent actual stage",()=>{
 assert.equal(client.stage("Waiting for official model unload"),"正在卸载语言模型");
 assert.equal(client.stage("Local Qwen-Image inference"),"正在使用 Qwen-Image 生成图片");
 assert.equal(client.stage("Restoring official text model"),"正在加载语言模型");
 assert.equal(client.stage("Restoring active KV snapshot"),"正在恢复 KV 缓存");
 assert.equal(client.stage("Real-ESRGAN 4x upscale"),"正在进行 4× 超分");
});
test("Native status distinguishes intentional engine unloading from service disconnect",()=>{
 const s=client.healthStage({component:"mikuchin-gateway",
    official_polystrata_reachable:false,
    native_gpu:{busy:true,phase:"unloading"},native_image_jobs:{running:1,phase:"Waiting for official model unload"}});
 assert.equal(s.text,"正在卸载语言模型");
 assert.equal(s.state,"reading");
 assert.equal(client.healthStage({component:"mikuchin-gateway",
    official_polystrata_reachable:false,native_gpu:{busy:false},native_image_jobs:{running:0}}).text,
    "推理引擎暂不可用");
});
test("Model decision placeholder is absent and thinking streams",()=>{
 assert.match(app,/m\.text="";\s*saveChat\(\); \/\/ Persist/);
 assert.match(app,/m\.reasoning\+=event\.reasoning/);
 assert.match(app,/m\.text\+=event\.text/);
 assert.match(html,/native-turn-stream\.js/);
});
test("Conversation switching detaches native request, and old result cannot overwrite current chat",()=>{
 assert.match(app,/function detachNativeTurnForNavigation\(\)/);
 assert.match(app,/if\(sessionId===responseSession\)\{/);
 assert.match(sessions,/!detachNativeTurnForNavigation\(\)/);
 assert.doesNotMatch(sessions.slice(0,sessions.indexOf("async function historyRequest")),/if \(busy \|\| intentRouting/);
});
