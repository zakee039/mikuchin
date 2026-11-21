import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {test} from "node:test";

const require=createRequire(import.meta.url);
const router=require("../chat-image-router.js");

test("direct Chinese and English image requests route to generation",()=>{
  for(const text of ["你好，生成一张初音未来的图片","帮我画一张小猫插画","给我做张壁纸",
    "Please generate an image of a teal-haired singer","Draw a picture of a dragon"]) {
    assert.equal(router.intent(text), "generate", text);
  }
});

test("questions, explanations, instructions and negations never charge an image job",()=>{
  for(const text of ["如何生成一张图片？","帮我解释生成图像的原理","不用生成图片，聊聊模型配置",
    "别画图，讲一下","你好","Tell me how to generate an image"]) {
    assert.equal(router.intent(text), "text", text);
  }
});

test("edit request only routes when the current session has an earlier generated image",()=>{
  assert.equal(router.intent("把刚才那张图的眼睛调大点",true),"edit");
  assert.equal(router.intent("把刚才那张图的眼睛调大点",false),"text");
  assert.equal(router.intent("把背景换成蓝色",true),"edit");
});

test("legacy tool envelopes are parsed as data only, never as runnable commands",()=>{
  const payload=JSON.stringify({action:"dalle.text2im",
    action_input:JSON.stringify({prompt:"Hatsune Miku with teal twintails"})});
  assert.deepEqual(router.tool(payload),{action:"generate",prompt:"Hatsune Miku with teal twintails"});
  assert.equal(router.looksLikeTool(payload),true);
  assert.equal(router.tool(JSON.stringify({action:"shell.run",action_input:{prompt:"del C:\\data"}})),null);
  assert.equal(router.tool('{"action":"dalle.text2im","action_input":"not-json"}'),null);
  assert.equal(router.tool("Here is how to use dalle.text2im"),null);
});
