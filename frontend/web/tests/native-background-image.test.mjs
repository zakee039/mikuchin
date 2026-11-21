import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";
const require=createRequire(import.meta.url);
const client=require("../native-tool-client.js");
const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const session="a".repeat(32),turn="b".repeat(32),image="c".repeat(32)+".png";
const initial=()=>({role:"assistant",text:"",reasoning:"",native_turn_id:turn,time:Date.now()});
const response=(state,extra={})=>({session_id:session,turn_id:turn,state,online:true,background:true,
  tool:{name:"generate_image",tool_call_id:"call_miku",arguments:{prompt:"初音未来"}},...extra});

test("online tool immediately acknowledges and remains free for subsequent user messages",()=>{
 const m=initial();
 client.apply(m,response("running",{job:{id:"img-test",state:"running",phase:"调用图像 API"}}));
 assert.equal(m.native_background,true);
 assert.match(m.text,/已经开始/);
 assert.equal(m.tools[0].round,null);
 assert.equal(m.tools[0].native_hide_image,true);
 assert.equal(client.unfinished(m),true);
 assert.match(app,/!x\.native_background &&/);
});
test("completed background picture is held for a later separate vision result",()=>{
 const m=initial();
 client.apply(m,response("running"));
 client.apply(m,response("vision_done",{text:"画好了，你看看！这张初音未来的双马尾...",
   job:{id:"img-test",state:"success",result:{image_file:image}}}));
 assert.equal(client.unfinished(m),false);
 assert.equal(m.native_completion_ready,true);
 assert.match(m.native_completion_text,/初音未来/);
 assert.equal(m.tools[0].round,null);
 assert.equal(m.tools[0].native_hide_image,true);
});
test("separate completion is idempotent and deferred while another answer is streaming",()=>{
 const source=app.slice(app.indexOf("function deliverNativeBackgroundCompletions()"),
   app.indexOf("async function submitModelToolTurn("));
 const origin=initial();
 origin.native_background=true;
 origin.native_completion_ready=true;
 origin.native_completion_text="画好了，看看初音未来";
 origin.tools=[{id:"call_miku",name:"generate_image",round:null,at:0,
   state:"done",native_turn_id:turn,image_file:image,native_hide_image:true,
   arguments:{prompt:"初音未来"},result:"Image generation succeeded."}];
 const concurrentReply={role:"assistant",text:"天气晴朗",time:Date.now()};
 const context={messages:[origin,concurrentReply],busy:{msg:concurrentReply},
   sessionId:session,saveChat:()=>{context.saves++},
   renderChat:()=>{},scrollDown:()=>{},saves:0};
 vm.runInNewContext(source+"\nthis.finish=deliverNativeBackgroundCompletions;",context);
 context.finish();
 assert.equal(context.messages.length,2);
 context.busy=null;
 context.finish();
 assert.equal(context.messages.length,3);
 assert.equal(context.messages[2].native_completion_of,turn);
 assert.equal(context.messages[2].tools[0].round,1);
 assert.equal(context.messages[2].tools[0].native_hide_image,false);
 assert.match(context.messages[2].text,/初音未来/);
 context.finish();
 assert.equal(context.messages.length,3);
 assert.equal(context.saves,1);
});
test("local exclusive mode never allows overlapping chat while image task is pending",()=>{
 const m=initial();
 client.apply(m,{...response("running"),online:false,background:false});
 assert.equal(m.native_background,undefined);
 assert.equal(m.text,"");
});
