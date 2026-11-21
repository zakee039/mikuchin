import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {createRequire} from "node:module";

const require=createRequire(import.meta.url);
const normalize=require("../reference-normalize.js");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const studio=readFileSync(new URL("../image-studio.js",import.meta.url),"utf8");

test("reference fix is loaded before the existing Images workspace, without changing its upload UI",()=>{
  assert.ok(html.indexOf("web/reference-normalize.js") < html.indexOf("web/image-studio.js"));
  assert.match(studio,/MikuchinReferenceNormalizer\.normalize\(file\)/);
  assert.match(studio,/reader\.readAsDataURL\(normalized\)/);
  assert.match(studio,/URL\.createObjectURL\(normalized\)/);
  assert.match(studio,/name: file\.name/);
  assert.equal(normalize.MAX_EDGE,2048);
  assert.ok(normalize.TARGET_BYTES*8*4/3 < 8*1024*1024);
});

test("browser decode+reencode preserves a browser-viewable corrupted metadata image",async()=>{
  const source=readFileSync(new URL("../reference-normalize.js",import.meta.url),"utf8");
  let bitmapClosed=false,canvasSize=null;
  const fakeCanvas={
    width:0,height:0,
    getContext(){return {drawImage(){canvasSize=[fakeCanvas.width,fakeCanvas.height]}};},
    toBlob(callback,type){callback({type:"image/webp",size:460_000});}
  };
  const window={};
  const context={
    window, module:{exports:{}},
    createImageBitmap:async file=>({
      width:4096,height:3072,close(){bitmapClosed=true;}
    }),
    document:{createElement:tag=>{assert.equal(tag,"canvas");return fakeCanvas;}},
    Math,Number,Set,Promise,Error,String
  };
  vm.runInNewContext(source,context);
  const blob=await window.MikuchinReferenceNormalizer.normalize({
    type:"image/png",size:1_000_000,
  });
  assert.equal(blob.type,"image/webp");
  assert.equal(blob.size,460_000);
  assert.ok(canvasSize[0]<=2048 && canvasSize[1]<=2048);
  assert.ok(canvasSize[0]*canvasSize[1]<=4_000_000);
  assert.equal(bitmapClosed,true);
});

test("rejects an unsupported or too-large file before bitmap decoding",async()=>{
  for(const file of [
    {type:"image/svg+xml",size:4096},
    {type:"image/png",size:0},
    {type:"image/jpeg",size:6*1024*1024}
  ])await assert.rejects(normalize.normalize(file),/仅支持/);
});
