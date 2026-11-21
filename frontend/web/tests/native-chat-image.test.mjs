import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";

const app=readFileSync(new URL("../app.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const characters=readFileSync(new URL("../characters.js",import.meta.url),"utf8");
const secure=readFileSync(new URL("../auth-images.js",import.meta.url),"utf8");

test("Native composer removes image generation and automatic image routing", () => {
  assert.doesNotMatch(html,/id="chat-draw-btn"/);
  assert.doesNotMatch(html,/id="chat-auto-btn"/);
  assert.doesNotMatch(html,/id="chat-image-confirm"/);
  assert.doesNotMatch(html,/web\/chat-image-intent\.js/);
  assert.doesNotMatch(app,/sendNativeChatImage|autoImageEnabled|intentRouting/);
  assert.match(html,/id="tab-btn-images"/);
  assert.match(app,/async function send\(\)/);
});test("Chat image polling matches by session and request ID, handles Native success/failed", () => {
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
});
