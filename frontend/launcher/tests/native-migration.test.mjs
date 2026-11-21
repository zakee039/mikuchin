import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
const source=readFileSync(new URL("../src/main.ts",import.meta.url),"utf8");
const rust=readFileSync(new URL("../src-tauri/src/native.rs",import.meta.url),"utf8");
const gateway=readFileSync(new URL("../../../backend/gateway/app.py",import.meta.url),"utf8");
const app=readFileSync(new URL("../../../frontend/web/app.js",import.meta.url),"utf8");

test("promoted Native launcher retains old-mixed configuration UX and language controls", () => {
  assert.match(source, /data-action="choose-config"/);
  assert.match(source, /data-action="view-config"/);
  assert.match(source, /config-picker-modal/);
  assert.match(source, /data-import-config/);
  assert.match(source, /config-modal/);
  assert.match(source, /id="api-key-display"/);
  assert.match(source, /value="\$\{esc\(keyCache\)\}"/);
  assert.match(source, /data-action="copy-key"/);
  assert.match(source, /data-action="rotate-key"/);
  assert.doesNotMatch(source, /API Key 已隐藏|轮换密钥前先卸载模型/);
  assert.match(source, /<h3>启动与守护<\/h3>/);
  assert.match(source, /<h3>全局语言<\/h3>/);
  assert.match(source, /<h3>空闲卸载时间<\/h3>/);
  assert.match(source, /id="idle-minutes"/);
  assert.match(source, /data-action="save-idle-timeout"/);
  assert.match(source, /get_native_language/);
  assert.match(source, /set_native_language/);
  assert.doesNotMatch(source, /id="native-model-select"|id="native-import-path"/);
  assert.match(rust, /const GATEWAY_PORT: u16 = 15239/);
  assert.match(rust, /const STABLE_PORT: u16 = 25239/);
  assert.match(rust, /PolyStrata v0\.1\.45-poly\.10/);
  assert.match(rust, /fn list_native_model_configs\(/);
});

test("Gateway about page shows unchanged pinned PolyStrata release suffix",()=>{
  assert.match(gateway,/official_polystrata_release.*v0\.1\.45-poly\.10/);
  assert.match(app,/health\?\.official_polystrata_release/);
});
