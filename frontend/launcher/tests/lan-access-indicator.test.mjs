import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";

const style=readFileSync(new URL("../src/style.css",import.meta.url),"utf8");
const nativeUi=readFileSync(new URL("../src/main.ts",import.meta.url),"utf8");
const prefs=readFileSync(new URL("../src-tauri/src/native_prefs.rs",import.meta.url),"utf8");
const network=readFileSync(new URL("../src-tauri/src/native_network.rs",import.meta.url),"utf8");
const supervisor=readFileSync(new URL("../../../backend/gateway/supervisor.py",import.meta.url),"utf8");

test("LAN toggle persists Native preferences with original switch styling",()=>{
  assert.match(nativeUi,/data-setting="lan_access"/);
  assert.match(nativeUi,/settings\?\.lan_access \? "checked" : ""/);
  assert.match(style,/\.api-compact \.toggle-compact input:checked \+ \.switch/);
  assert.match(prefs,/lan_access: false/);
});
test("Gateway LAN opt-in never exposes official PolyStrata engine",()=>{
  assert.match(nativeUi,/局域网 HTTP 直连/);
  assert.match(supervisor,/--lan-access/);
  assert.match(supervisor,/127\.0\.0\.1/);
  assert.match(network,/GetAllNetworkInterfaces/);
});
test("Native LAN renders reachable adapter addresses and keeps pending entries non-clickable",()=>{
  assert.match(nativeUi,/lan-address-list/);
  assert.match(nativeUi,/const lanEntries = settings\?\.lan_access/);
  assert.match(nativeUi,/lan_addresses \|\| \[\]/);
  assert.match(nativeUi,/lanReady\s*\?/);
  assert.match(nativeUi,/lan-chat-inactive/);
  assert.match(nativeUi,/class="lan-chat-link"/);
  assert.match(nativeUi,/Tailscale/);
  assert.match(nativeUi,/Wi-Fi/);
});
test("Native excludes link-local and loopback IPv4 addresses",()=>{
  assert.match(network,/!ip\.is_loopback\(\)/);
  assert.match(network,/!ip\.is_link_local\(\)/);
  assert.match(network,/!ip\.is_multicast\(\)/);
  assert.match(nativeUi,/未检测到可用的 IPv4 网卡地址/);
});
