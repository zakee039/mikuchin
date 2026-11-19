import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const ui = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const native = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

test("LAN access toggle renders the persisted setting, including its on-state", () => {
  assert.match(ui, /data-setting="lan_access"/);
  assert.match(ui, /prefs\?\.lan_access\?"checked":""/);
  assert.match(css, /\.api-compact \.toggle-compact input:checked \+ \.switch\s*\{[^}]*background:/);
  assert.match(css, /\.api-compact \.toggle-compact input:checked \+ \.switch:before\s*\{[^}]*translateX/);
});

test("direct LAN exposure is described as HTTP and the default is loopback", () => {
  assert.match(ui, /局域网 HTTP 直连/);
  assert.match(native, /lan_access:\s*false/);
  assert.match(native, /if p\.lan_access \{ "0\.0\.0\.0" \} else \{ "127\.0\.0\.1" \}/);
});

test("enabled LAN displays every active adapter as a clickable Chat address", () => {
  assert.match(ui, /function lanChatLinks\(/);
  assert.match(ui, /lan_addresses/);
  assert.match(ui, /addresses\.map\(a=>/);
  assert.match(ui, /class="lan-chat-link"/);
  assert.match(ui, /!prefs\?\.lan_access/);
  assert.match(native, /fn active_lan_addresses\(/);
  assert.match(native, /"lan_addresses":lan_addresses/);
  assert.match(native, /if prefs\.lan_access \{/);
  assert.match(native, /GetAllNetworkInterfaces/);
  assert.match(native, /OperationalStatus\]::Up/);
  assert.match(native, /Duration::from_secs\(10\)/);
  assert.match(css, /\.lan-address-entry/);
});

test("hotspot adapters are labeled and unusable IPv4 addresses are excluded", () => {
  assert.match(ui, /wi-fi direct virtual adapter/);
  assert.match(ui, /"移动热点"/);
  assert.match(native, /!ip\.is_loopback\(\)/);
  assert.match(native, /!ip\.is_link_local\(\)/);
  assert.match(native, /!ip\.is_multicast\(\)/);
  assert.match(ui, /HTTP 服务尚未就绪/);
});
