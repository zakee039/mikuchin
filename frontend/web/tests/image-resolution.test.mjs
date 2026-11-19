import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import {test} from "node:test";

const require = createRequire(import.meta.url);
const resolution = require("../image-resolution.js");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const studio = readFileSync(new URL("../image-studio.js", import.meta.url), "utf8");

test("all eight standards are distinct WIDTH x HEIGHT, with correct orientation", () => {
  const expected = ["1024x1024","2048x2048","1536x1024","1024x1536",
    "1536x864","2560x1440","3840x2160","2160x3840"];
  assert.deepEqual(resolution.standard.map(item => item.size), expected);
  for (const size of expected) {
    const result = resolution.dimensions({family:"api",sizes:"standard"}, {standard:size});
    assert.equal(result.size, size);
    assert.equal(result.size, `${result.width}x${result.height}`);
  }
  assert.equal(resolution.dimensions({family:"api",sizes:"standard"},
    {standard:"1536x1024"}).width, 1536);
  assert.equal(resolution.dimensions({family:"api",sizes:"standard"},
    {standard:"1024x1536"}).height, 1536);
});

test("local suggestions have no 1536 and preserve WIDTH x HEIGHT orientation", () => {
  assert.deepEqual([...resolution.local],[384,512,768,1024]);
  assert.equal(resolution.dimensions({family:"qwen_turbo"}, {width:"1024",height:"512"}).size,"1024x512");
  assert.equal(resolution.dimensions({family:"api",sizes:"all"}, {width:"384",height:"1024"}).size,"384x1024");
  assert.equal(resolution.dimensions({family:"api",sizes:"square"}, {}).size,"1024x1024");
});

test("custom width and height independently snap to nearest 16 and clamp", () => {
  for (const [input,expected] of [[1000,1008],[1025,1024],[1537,1536],[999999,4096],[0,256],[-10,256]])
    assert.equal(resolution.nearest16(input),expected,String(input));
  assert.equal(resolution.nearest16(""),1024);
  assert.equal(resolution.dimensions({family:"api",sizes:"custom"},
    {customWidth:1000,customHeight:1500}).size,"1008x1504");
});

test("Image Studio and chat controls show width first and height second", () => {
  for (const prefix of ["img", "global-chat-image"]) {
    const widthAt=html.indexOf(`id="${prefix}-width"`);
    const heightAt=html.indexOf(`id="${prefix}-height"`);
    assert.ok(widthAt>=0 && heightAt>=0 && widthAt<heightAt,prefix);
    assert.match(html.slice(Math.max(0,widthAt-100),widthAt),/>宽\s*<select/);
    assert.match(html.slice(Math.max(0,heightAt-100),heightAt),/>高\s*<select/);
  }
  assert.match(studio,/size: currentSize\(\)\.size/);
  assert.match(studio,/requested_size:currentSize\(\)\.size/);
});

test("the shared size definitions are loaded before both user interfaces", () => {
  assert.ok(html.indexOf('web/image-resolution.js') < html.indexOf('web/image-studio.js'));
  assert.ok(html.indexOf('web/image-resolution.js') < html.indexOf('web/characters.js'));
  assert.match(html, /<option value="custom">自定义/);
});
