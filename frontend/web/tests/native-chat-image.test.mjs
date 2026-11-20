import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";

const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const characters=readFileSync(new URL("../characters.js",import.meta.url),"utf8");
const secure=readFileSync(new URL("../auth-images.js",import.meta.url),"utf8");

test("Native chat image generation requires an explicit visible button and a second confirmation", () => {
  assert.match(html,/id="chat-draw-btn"[^>]*hidden/);
  assert.match(html,/id="chat-image-confirm-yes"/);
  assert.match(html,/id="chat-image-confirm-no"/);
  assert.match(app,/\$\("chat-draw-btn"\)\.onclick=.*sendNativeChatImage/);
  assert.match(app,/const accepted=await confirmNativeChatImage\(cfg\)/);
  assert.match(app,/if \(!accepted\) return/);
  const textSend=app.split("async function send() {")[1].split('logPlaceholder')[0];
  assert.doesNotMatch(textSend.slice(0,2500),/chat_submit/);
});
test("Browser sends exactly one authorized chat_submit with a durable client ID", () => {
  assert.match(app,/const currentId=sessionId, requestId=makeSessionId\(\)/);
  assert.match(app,/image_request_id:requestId/);
  assert.ok(app.indexOf("saveChat();renderChat();") < app.indexOf('action:"chat_submit"'));
  assert.match(app,/action:"chat_submit",session_id:currentId/);
  assert.match(app,/m\.tools\[0\]\.image_job_id=job\.id/);
  assert.match(app,/不会自动重复提交/);
});
test("Chat image polling matches by session and request ID, handles Native success/failed", () => {
  assert.match(app,/image_request_id\) && t\.state === "running"/);
  assert.match(app,/requests\.get\(t\.image_request_id\)/);
  assert.match(app,/\["done","error","interrupted","success","failed"\]/);
  assert.match(app,/image_original_file:\s*picture\.image_original_file/);
  assert.match(app,/chat_cancel/);
  assert.match(app,/仅取消尚未执行的排队任务/);
});
test("Native images use authenticated Blob URLs instead of bare image URLs or secrets", () => {
  assert.match(app,/data-native-image-src/);
  assert.match(app,/\|\| !!t\.image_request_id/);
  assert.match(app,/MikuchinSecureImages\.load/);
  assert.match(app,/MikuchinSecureImages\.prefetch/);
  assert.match(secure,/Authorization/);
  assert.match(secure,/URL\.createObjectURL/);
  assert.doesNotMatch(app,/image_file.*api[_-]?key/i);
});
test("Native vision is one bounded local follow-up with no thinking or new image tool", () => {
  assert.match(app,/t\.vision_state="requested"/);
  assert.match(app,/async function describeNativeChatImage/);
  assert.match(app,/max_tokens:256/);
  assert.match(app,/reasoning_effort:"none"/);
  assert.match(app,/strata_image_tool:false,strata_mcp:false/);
  assert.match(app,/canvas\.toDataURL\("image\/jpeg",0\.8\)/);
  assert.match(app,/tool\.vision_state="done"/);
  assert.match(app,/tool\.vision_state="failed"/);
  assert.match(characters,/polyNativeChatImageRequest/);
  assert.match(characters,/characterState\.global\.chat_image_settings/);
  assert.match(characters,/selected === "default"/);
  assert.match(characters,/model\.family === "api"/);
  assert.match(app,/首次使用默认本地模型/);
});
