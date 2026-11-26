import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";

const file = name => readFileSync(new URL("../" + name, import.meta.url), "utf8");
const versionsSource=file("versions.js");
const gatewaySource=readFileSync(new URL("../../../backend/gateway/app.py",import.meta.url),"utf8");
const pin=gatewaySource.match(/"official_polystrata_release": "(v\d+\.\d+\.\d+-poly\.\d+)"/)[1];
const app=file("app.js");
const index=file("index.html");

test("official PolyStrata pin is embedded before app loads", () => {
  const window={};
  vm.runInNewContext(versionsSource,{window});
  assert.equal(window.MIKUCHIN_VERSIONS.polystrata,pin);
  const versions=JSON.parse(readFileSync(new URL("../../../versions.json",import.meta.url),"utf8"));
  assert.equal(window.MIKUCHIN_VERSIONS.main,versions.components.main.version);
  assert.ok(index.indexOf('web/versions.js') < index.indexOf('web/app.js'));
});

test("About page shows full official pin immediately, even without metrics or health", () => {
  const source=app.slice(app.indexOf("function renderAbout("),
                         app.indexOf('document.addEventListener("click"',app.indexOf("function renderAbout(")));
  assert.ok(source.startsWith("function renderAbout"));
  assert.doesNotMatch(source,/health\?/);
  assert.doesNotMatch(source,/eng\.version/);
  const tables={};
  const window={};
  vm.runInNewContext(versionsSource,{window});
  const ctx={window,location:{origin:"http://localhost:15239"},
             $:id=>id,facts:(id,rows)=>{tables[id]=rows;},
             fmt:x=>String(x),gb:x=>String(x),projectionText:()=>null};
  vm.runInNewContext(source + "\nthis.render=renderAbout;",ctx);
  ctx.render({},{},{});
  const engine=tables["facts-engine"].find(([name])=>name==="Engine");
  assert.equal(engine[1],`PolyStrata ${pin}`);
  ctx.health={component:"mikuchin-gateway",official_polystrata_release:"v0.1.45",
              official_polystrata_reachable:false};
  ctx.render({version:"0.1.45"},{},{});
  assert.equal(tables["facts-engine"].find(([name])=>name==="Engine")[1],
               `PolyStrata ${pin}`);
});

test("navigating to About does not wait for the first metrics poll", () => {
  assert.match(app,/else if \(tab === "about"\) renderAbout\(\{\}, \{\}, \{\}\)/);
  assert.match(index,/web\/app\.js\?v=[a-zA-Z0-9.-]+/);
});
