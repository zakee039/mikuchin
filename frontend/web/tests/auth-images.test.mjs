import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createContext,runInContext} from "node:vm";
import {test} from "node:test";

const source=readFileSync(new URL("../auth-images.js",import.meta.url),"utf8");
const gallery=readFileSync(new URL("../gallery.js",import.meta.url),"utf8");
const studio=readFileSync(new URL("../image-studio.js",import.meta.url),"utf8");
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");

function setup() {
  const calls=[], revoked=[];
  let uid=0;
  let token="Bearer private-key";
  const scope={
    window:{}, Blob, Map, WeakMap, URL:{
      createObjectURL:()=>"blob:mock-"+(++uid),
      revokeObjectURL:url=>revoked.push(url)
    },
    headers:()=>({Authorization:token}),
    fetch:async(url,options)=>{
      calls.push([url,options]);
      return {ok:true,status:200,headers:{get:()=>"8"},
        blob:async()=>new Blob(["12345678"],{type:"image/png"})};
    },
  };
  createContext(scope);
  runInContext(source,scope);
  function image(){
    const attributes=new Map();
    return {
      set src(value){attributes.set("src",value);},
      get src(){return attributes.get("src")||"";},
      removeAttribute(name){attributes.delete(name);},
      getAttribute(name){return attributes.get(name)||null},
    };
  }
  return {api:scope.window.MikuchinSecureImages,calls,revoked,image,
    setToken:value=>{token=value;}};
}

test("private image fetch sends a Bearer header but img.src gets only a blob URL",async()=>{
  const {api,calls,image}=setup(), img=image();
  await api.load(img,"v1/images/files/"+"a".repeat(32)+".png");
  assert.match(img.src,/^blob:mock-\d+$/);
  assert.equal(calls.length,1);
  assert.equal(calls[0][1].headers.Authorization,"Bearer private-key");
  assert.equal(calls[0][1].cache,"no-store");
  assert.equal(calls[0][0],"v1/images/files/"+"a".repeat(32)+".png");
});

test("releasing/removing a private image revokes the object URL",async()=>{
  const {api,revoked,image}=setup(), img=image();
  const first="v1/mikuchin/gallery/thumb/"+"b".repeat(32);
  await api.load(img,first);
  assert.equal(api.path(img),first);
  const old=img.src;
  api.release(img);
  assert.equal(api.path(img),"");
  assert.equal(img.src,"");
  assert.deepEqual(revoked,[old]);
});

test("an out-of-order image response cannot replace the newest frame",async()=>{
  const {api,calls,image}=setup(),img=image();
  const older="v1/images/files/"+"c".repeat(32)+".png";
  const newer="v1/images/files/"+"d".repeat(32)+".png";
  const p1=api.load(img,older),p2=api.load(img,newer);
  await Promise.all([p1,p2]);
  assert.equal(api.path(img),newer);
  assert.ok(img.src.startsWith("blob:"));
  assert.equal(calls.length,2);
});

test("path allowlist prevents arbitrary URL fetches and key exfiltration",async()=>{
  const {api,calls,image}=setup();
  for (const input of ["https://attacker.example/collect","//attacker.example/path",
    "v1/images/files/../private","v1/images/files/"+"a".repeat(32)+".png?key=secret"]){
    await assert.rejects(()=>api.load(image(),input),/invalid/);
  }
  assert.equal(calls.length,0);
});

test("switching API identity clears private bytes and revokes visible URLs",async()=>{
  const {api,calls,revoked,image,setToken}=setup();
  const img=image();
  const path="v1/mikuchin/gallery/thumb/"+"e".repeat(32);
  await api.load(img,path);
  const old=img.src;
  setToken("Bearer another-private-user");
  await api.prefetch(path);
  assert.equal(img.src,"");
  assert.deepEqual(revoked,[old]);
  assert.equal(calls.length,2);
  assert.equal(calls[1][1].headers.Authorization,"Bearer another-private-user");
});

test("gallery and task UI use authenticated image loading, not raw protected URLs",()=>{
  assert.match(gallery,/secure\.load\(img,api \+ "\/thumb\/"/);
  assert.match(gallery,/secure\.load\(full,nextSrc\)/);
  assert.match(studio,/MikuchinSecureImages\.load\(thumbnail/);
  assert.match(studio,/MikuchinSecureImages\.load\(img/);
  assert.ok(html.indexOf("web/auth-images.js")<html.indexOf("web/gallery.js"));
  assert.ok(html.indexOf("web/auth-images.js")<html.indexOf("web/image-studio.js"));
});
