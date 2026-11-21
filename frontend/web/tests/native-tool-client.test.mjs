import assert from "node:assert/strict";
import test from "node:test";
import {createRequire} from "node:module";
import {readFileSync} from "node:fs";
const require=createRequire(import.meta.url);
const client=require("../native-tool-client.js");
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const session="a".repeat(32), turn="b".repeat(32), image="c".repeat(32)+".png";
const basic=(state,options={})=>({session_id:session,turn_id:turn,state,text:"",
  tool:{name:"generate_image",tool_call_id:"call_001",arguments:{prompt:"a cat"}},
  online:false,profile_id:"local-qwen-official",...options});
const msg=()=>({role:"assistant",text:"",native_turn_id:turn,native_tool_state:"deciding",time:Date.now()});

test("waiting decision renders no executable tool and stays resumable",()=>{
 const m=msg();
 client.apply(m,{session_id:session,turn_id:turn,state:"deciding"});
 assert.equal(m.tools,null);
 assert.equal(client.unfinished(m),true);
});

test("native model tool decision becomes a single renderable job",()=>{
 const m=msg();
 client.apply(m,basic("running",{job_id:"img-123",job:{id:"img-123",state:"running",phase:"正在加载生图模型"}}));
 assert.equal(m.tools.length,1);
 assert.equal(m.tools[0].name,"generate_image");
 assert.equal(m.tools[0].image_job_id,"img-123");
 assert.equal(m.tools[0].state,"running");
 assert.equal(client.unfinished(m),true);
});

test("image appears during the independent local vision tail and survives failure",()=>{
 const m=msg();
 client.apply(m,basic("vision_running",{job:{id:"img-123",state:"success",
   result:{image_file:image,upscale_original_id:"d".repeat(32)}}}));
 assert.equal(m.tools[0].image_file,image);
 assert.equal(m.tools[0].image_original_file,"d".repeat(32)+".png");
 assert.equal(client.unfinished(m),true);
 client.apply(m,basic("vision_failed",{text:"图片已生成，但视觉理解未完成。",
   job:{id:"img-123",state:"success",result:{image_file:image}}}));
 assert.equal(client.unfinished(m),false);
 assert.equal(m.tools[0].image_file,image);
 assert.equal(m.tools[0].round,1);
});

test("tool-free answer remains ordinary chat and terminal",()=>{
 const m=msg();
 client.apply(m,{session_id:session,turn_id:turn,state:"text_done",text:"这是一个解释性回答"});
 assert.equal(m.tools,null);
 assert.equal(m.text,"这是一个解释性回答");
 assert.equal(client.unfinished(m),false);
});

test("legacy dalle tool-shaped text is nonexecutable and diagnosed",()=>{
 const m=msg();
 client.apply(m,{session_id:session,turn_id:turn,state:"text_done",
   text:JSON.stringify({action:"dalle.text2im",action_input:{prompt:"cat"}})});
 assert.equal(m.tools,null);
 assert.match(m.text,/未提交图像任务/);
 assert.equal(client.unfinished(m),false);
});

test("paid provider requires explicit consent before dispatch",()=>{
 const m=msg();
 client.apply(m,basic("awaiting_approval",{online:true}));
 assert.equal(m.tools[0].state,"writing");
 assert.equal(client.unfinished(m),true);
 assert.match(m.tools[0].result,/在线生图授权/);
 client.apply(m,basic("cancelled",{text:"用户取消"}));
 assert.equal(m.tools[0].state,"error");
 assert.equal(client.unfinished(m),false);
});

test("client never accepts cross-turn replacement",()=>{
 assert.throws(()=>client.apply(msg(),{session_id:session,turn_id:"f".repeat(32),
   state:"vision_done"}),/does not belong/);
});

test("composer code uses one POST and then read-only GET polling",()=>{
 const native=app.slice(app.indexOf("async function submitModelToolTurn("),
   app.indexOf("async function submitAutoChatImage("));
 assert.match(app,/method:"POST",headers:\{\.\.\.headers\(true\),Accept:"text\/event-stream"/);
 assert.match(native,/nativeTurnPath\(m\.native_turn_id\)/);
 assert.match(native,/receiveNativeToolStream\(request,m,el,fixedSession\)/);
 assert.doesNotMatch(native,/MikuchinChatImageRouter/);
 assert.doesNotMatch(native,/submitAutoChatImage/);
});

test("running image tool displays Status, never Error while generating",()=>{
 assert.match(app,/t\.state === "running" \|\| t\.state === "writing" \? "Status"/);
 assert.match(app,/t\.arguments == null \? "" : JSON\.stringify\(t\.arguments/);
});
