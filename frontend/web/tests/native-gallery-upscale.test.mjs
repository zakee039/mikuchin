import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
const gallery=readFileSync(new URL("../gallery.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
test("gallery exposes 4x only when unpaired and native worker is configured",()=>{
  assert.match(gallery,/gallery-create-upscale/);
  assert.match(gallery,/action\.hidden=pair \|\|/);
  assert.match(gallery,/native_upscaler_ready === false/);
  assert.match(gallery,/\["queued","working","running"\]/);
  assert.match(gallery,/\["done","success"\]/);
  assert.doesNotMatch(gallery,/has not been ported yet/);
  assert.match(html,/gallery\.js\?v=20261120-native-manual-upscale/);
});
test("manual gallery job only requests offline upscale on an existing image",()=>{
  assert.match(gallery,/body:JSON\.stringify\(\{kind:"upscale",image_id:item\.id\}\)/);
  assert.match(gallery,/upscaleJobs\.set\(item\.id,job\)/);
  assert.match(gallery,/updateUpscaledItem\(job\.source_id\)/);
});
