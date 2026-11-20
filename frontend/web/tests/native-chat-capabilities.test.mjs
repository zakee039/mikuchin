import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import {test} from "node:test";

const require = createRequire(import.meta.url);
const compat = require("../chat-capabilities.js");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const studio = readFileSync(new URL("../image-studio.js", import.meta.url), "utf8");

test("Native Image Studio remains available without enabling unsupported chat image tool", () => {
  const body = {messages:[], stream:true, reasoning_budget_tokens:1024};
  const result = compat.apply(body, {
    image_generation:true, chat_image_tool:false, answer_budget_tokens:false, chat_mcp:false,
  }, {max:"", mcp:true}, {stateless:false,mcpTools:4});
  assert.equal(result, body);
  assert.equal(body.strata_image_tool, undefined);
  assert.equal(body.strata_mcp, undefined);
  assert.equal(body.answer_budget_tokens, undefined);
  assert.equal(body.reasoning_budget_tokens, 1024);
});

test("Legacy Mikuchin without feature flags retains image and MCP tool request behavior", () => {
  const body = compat.apply({messages:[]},
    {image_generation:true}, {max:"256", mcp:true}, {stateless:false,mcpTools:1});
  assert.equal(body.strata_image_tool,true);
  assert.equal(body.strata_mcp,true);
  assert.equal(body.answer_budget_tokens,256);
});

test("Missing native capabilities never silently become max_tokens", () => {
  const body = {messages:[], reasoning_budget_tokens:4096};
  assert.throws(() => compat.apply(body, {answer_budget_tokens:false,image_generation:true},
    {max:"128"}, {stateless:false,mcpTools:0}), /尚不支持独立正文 Token 上限/);
  assert.equal(body.max_tokens, undefined);
  assert.equal(body.answer_budget_tokens, undefined);
  assert.equal(body.reasoning_budget_tokens, 4096);
});

test("Answer cap validates range, disabled default remains usable", () => {
  for (const value of [0, -1, 1.25, "NaN", 262145]) {
    assert.throws(() => compat.apply({}, {}, {max:value}), /integer/);
  }
  assert.equal(compat.apply({}, {answer_budget_tokens:false}, {max:""}).answer_budget_tokens,
               undefined);
  assert.equal(compat.apply({}, {}, {max:"1"}).answer_budget_tokens,1);
});

test("Stateless and MCP-disabled requests never enable unrequested tools", () => {
  const health = {image_generation:false,chat_mcp:true};
  const body = compat.apply({}, health, {max:"",mcp:true}, {stateless:true,mcpTools:20});
  assert.equal(body.strata_mcp,undefined);
  assert.equal(body.strata_image_tool,undefined);
});

test("Native official MCP tools activate only when advertised and opted in", () => {
  const health = {image_generation:true,chat_image_tool:false,chat_mcp:true};
  const enabled = compat.apply({},health,{max:"",mcp:true},{stateless:false,mcpTools:2});
  assert.equal(enabled.strata_mcp,true);
  assert.equal(enabled.strata_image_tool,undefined);
  const empty = compat.apply({},health,{max:"",mcp:true},{stateless:false,mcpTools:0});
  assert.equal(empty.strata_mcp,undefined);
  const optedOut = compat.apply({},health,{max:"",mcp:false},{stateless:false,mcpTools:2});
  assert.equal(optedOut.strata_mcp,undefined);
});

test("Capability shim is loaded before main app and Image Studio keeps explicit tool opt-out", () => {
  assert.ok(html.indexOf('web/chat-capabilities.js') < html.indexOf('web/app.js'));
  assert.match(app,/MikuchinChatCapabilities\.apply\(body, health, settings/);
  assert.match(html,/id="s-max-support"/);
  assert.match(app,/answer_budget_tokens === false/);
  assert.match(studio,/mikuchin_stateless: true, strata_image_tool: false/);
});
