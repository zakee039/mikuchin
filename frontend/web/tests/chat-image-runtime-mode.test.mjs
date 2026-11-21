import assert from "node:assert/strict";
import {test} from "node:test";
import {readFileSync} from "node:fs";
const file=name=>readFileSync(new URL("../"+name,import.meta.url),"utf8");
const html=file("index.html"), characters=file("characters.js"),
 gallery=file("gallery.js"), css=file("app.css");

test("Chat image runtime mode is beside model selector in global UI, not LLM model JSON",()=>{
 const row=html.slice(html.indexOf('class="chat-image-model-mode-row"'),
                      html.indexOf('id="global-chat-image-runtime-note"'));
 assert.match(row,/global-chat-image-profile/);
 assert.match(row,/global-chat-image-runtime-mode/);
 assert.match(row,/value="exclusive"/);
 assert.match(row,/value="concurrent"/);
 assert.match(css,/chat-image-model-mode-row/);
});
test("Native image runtime mode is autosaved, defaults safely to exclusive",()=>{
 assert.match(characters,/runtime_mode:"exclusive"/);
 assert.match(characters,/runtime_mode:\$\("global-chat-image-runtime-mode"\)\.value/);
 assert.match(characters,/"global-chat-image-runtime-mode"\]\)/);
 assert.match(characters,/mode\.disabled=!chatImageModelsReady \|\| selected\?\.family==="api"/);
});
test("Full-screen viewer buttons float above image, gallery adds download",()=>{
 const preview=file("chat-image-viewer.css");
 assert.match(preview,/position:absolute;z-index:3/);
 assert.match(preview,/background:transparent/);
 assert.match(preview,/position:absolute;inset:0/);
 assert.match(html,/id="gallery-viewer-download"/);
 assert.match(gallery,/gallery-viewer-download/);
 assert.match(gallery,/secure\.prefetch\(path\)/);
});
