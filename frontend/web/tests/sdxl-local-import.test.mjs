import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
const text=name=>readFileSync(new URL("../"+name,import.meta.url),"utf8");
const html=text("index.html"),importer=text("local-model-settings.js"),
      studio=text("image-studio.js"),characters=text("characters.js"),
      client=text("native-tool-client.js");
test("SDXL import is explicit single-checkpoint branch, not Qwen components",()=>{
 assert.match(html,/id="mk-local-family"/);
 assert.match(html,/<option value="sdxl">/);
 assert.match(html,/id="mk-local-checkpoint"/);
 assert.match(importer,/family:"sdxl",checkpoint:get\("mk-local-checkpoint"\)/);
 assert.match(importer,/mk-local-qwen/);
 assert.match(importer,/mk-local-sdxl/);
 assert.match(importer,/get\("mk-local-checkpoint"\)\.required=sdxl/);
});
test("SDXL gallery and chat model selectors use the common catalog",()=>{
 assert.match(studio,/model\(\)\?\.family === "sdxl"/);
 assert.match(studio,/referenceMode\(\)/);
 assert.match(characters,/next\.steps/);
 assert.match(client,/Local SDXL inference/);
});
