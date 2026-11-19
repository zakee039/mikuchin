import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../gallery.js", import.meta.url), "utf8");
function functionBlock(start, end) {
  const begin = source.indexOf(start);
  const finish = source.indexOf(end, begin);
  assert.ok(begin >= 0 && finish > begin, `function boundaries: ${start}`);
  return source.slice(begin, finish);
}

const viewerCode = functionBlock("  function showViewer() {", "  function setChrome(visible) {");
const preloadCode = functionBlock("  function prefetchNeighbors() {", "  const sourceLabel =");
const loadCode = functionBlock("  async function load(reset = true) {", "  function open(index) {");

function mockElement(name, changes) {
  const attributes = new Map();
  const classes = new Set();
  return {
    name, hidden: false, textContent: "", complete: false, naturalWidth: 0,
    classList: {
      add(c) {classes.add(c);}, remove(c) {classes.delete(c);},
      contains(c) {return classes.has(c);},
      toggle(c, enabled) {
        const result = enabled === undefined ? !classes.has(c) : Boolean(enabled);
        if (result) classes.add(c); else classes.delete(c);
        return result;
      },
    },
    setAttribute(k, v) {attributes.set(k, String(v));},
    getAttribute(k) {return attributes.get(k) ?? null;},
    removeAttribute(k) {attributes.delete(k);},
    set src(v) {changes.push([name, "src", v]); attributes.set("src", v);},
    get src() {return attributes.get("src") ?? "";},
  };
}

function harness() {
  const changes = [], nodes = new Map();
  const el = id => {
    if (!nodes.has(id)) nodes.set(id, mockElement(id, changes));
    return nodes.get(id);
  };
  const ctx = {
    $g: el, api: "v1/mikuchin/gallery", items: [], total: 0, lightbox: 0,
    zoom: 1, revealed: false, visibleNsfw: false, variant: "upscaled",
    expectedFullSrc: "", upscaleJobs: new Map(), loading: false,
    masked(item) {return Boolean(item.nsfw && !ctx.visibleNsfw);},
    fullSrc(item, variant) {
      return `v1/images/files/${variant === "original" && item.variants?.original ? item.variants.original : item.id}.png`;
    },
    resetZoom() {changes.push(["zoom", "reset"]);},
    translate(x) {return x;}, dateLabel() {return "today";}, sourceLabel(x) {return x;},
    clampPan() {}, applyZoom() {}, prefetchNeighbors() {changes.push(["prefetch"]);},
    checkUpscaleJobs() {},
    load() {changes.push(["request-next-page"]);return new Promise(() => {});},
    changes, nodes,
  };
  vm.createContext(ctx);
  vm.runInContext(viewerCode, ctx, {filename:"gallery.js viewer"});
  return ctx;
}

test("swiping past the loaded page paints target immediately, without awaiting fetch", () => {
  const ctx = harness();
  ctx.items = [{id:"a"},{id:"b"}];
  ctx.total = 4;
  ctx.lightbox = 1;
  ctx.shift(1);
  assert.equal(ctx.lightbox, 2);
  assert.equal(ctx.$g("gallery-position").textContent, "3 / 4");
  assert.equal(ctx.$g("gallery-image-loading").hidden, false);
  assert.equal(ctx.$g("gallery-image-loading").textContent, "正在获取下一张…");
  assert.deepEqual(ctx.changes.slice(-1), [["request-next-page"]]);
  ctx.loading = true;
  ctx.shift(1);
  assert.equal(ctx.lightbox, 3, "another swipe also remains responsive during loading");
  ctx.shift(-1);
  ctx.shift(-1);
  assert.equal(ctx.lightbox, 1, "swiping backwards works before the fetch finishes");
  assert.equal(ctx.$g("gallery-full").getAttribute("src"), "v1/images/files/b.png");
});

test("viewer displays the requested thumbnail before initiating full-image load", () => {
  const ctx = harness();
  ctx.items = [{id:"a"},{id:"b",nsfw:true}];
  ctx.total = 2;
  ctx.lightbox = 1;
  ctx.showViewer();
  const preview = ctx.$g("gallery-preview");
  const full = ctx.$g("gallery-full");
  assert.equal(preview.hidden, false);
  assert.equal(preview.src, "v1/mikuchin/gallery/thumb/b");
  assert.equal(full.src, "v1/images/files/b.png");
  assert.equal(ctx.$g("gallery-image-loading").hidden, false);
  assert.equal(ctx.$g("gallery-viewer-spoiler").hidden, false);
  assert.equal(preview.classList.contains("gallery-blurred"), true, "NSFW preview stays blurred");
  const thumbnailAssigned = ctx.changes.findIndex(x => x[0] === "gallery-preview" && x[1] === "src");
  const fullAssigned = ctx.changes.findIndex(x => x[0] === "gallery-full" && x[1] === "src");
  assert.ok(thumbnailAssigned >= 0 && fullAssigned > thumbnailAssigned);
  full.complete = true;
  full.naturalWidth = 1024;
  ctx.finishFullImage();
  assert.equal(preview.hidden, true);
  assert.equal(ctx.$g("gallery-image-loading").hidden, true);
  assert.equal(full.classList.contains("gallery-full-loading"), false);
  assert.deepEqual(ctx.changes.slice(-1), [["prefetch"]]);
});

test("preload keeps only the previous and next full images", () => {
  const events = [], tasks = [];
  const ctx = {
    lightbox: 1, items: [{id:"a"},{id:"b"},{id:"c"},{id:"d"}],
    total: 4, loading: false, preloadTimer:null,
    neighborPreloads: new Map(),
    fullSrc(item) {return `/files/${item.id}.png`;},
    Image: class {set src(v) {events.push(v);}},
    setTimeout(callback) {tasks.push(callback);return tasks.length;},
    clearTimeout() {}, load() {throw Error("unwanted page load");},
  };
  vm.createContext(ctx);
  vm.runInContext(preloadCode, ctx);
  ctx.prefetchNeighbors();
  tasks.shift()();
  assert.deepEqual(events, ["/files/a.png","/files/c.png"]);
  assert.equal(ctx.neighborPreloads.size, 2);
  ctx.lightbox = 2;
  ctx.prefetchNeighbors();
  tasks.shift()();
  assert.deepEqual([...ctx.neighborPreloads.keys()], ["/files/b.png","/files/d.png"]);
  assert.equal(ctx.neighborPreloads.size, 2);
});

test("a fetched metadata page fills the pending slot without rebuilding gallery grid", async () => {
  const ctx = harness();
  const painted = [];
  let resolveFetch;
  ctx.items = [{id:"a"},{id:"b"}];
  ctx.total = 4;
  ctx.lightbox = 2;
  ctx.fetchVersion = 0;
  ctx.selected = new Set();
  ctx.limit = 60;
  ctx.api = "v1/mikuchin/gallery";
  ctx.URLSearchParams = URLSearchParams;
  ctx.headers = () => ({});
  ctx.toast = () => assert.fail("unexpected failure");
  ctx.render = () => painted.push("grid rebuilt");
  ctx.fetch = () => new Promise(resolve => {resolveFetch = resolve;});
  ctx.$g("gallery-source").value = "all";
  ctx.$g("gallery-order").value = "newest";
  const originalShowViewer = ctx.showViewer;
  ctx.showViewer = () => {
    painted.push("pending slot filled");
    originalShowViewer();
  };
  ctx.setTimeout = () => assert.fail("a second page should not be required");
  vm.runInContext(loadCode, ctx, {filename:"gallery.js load"});
  const task = ctx.load(false);
  assert.equal(ctx.lightbox, 2, "target position exists before response");
  assert.equal(ctx.loading, true);
  resolveFetch({ok:true,json:async () => ({total:4,items:[{id:"c"},{id:"d"}]})});
  await task;
  assert.equal(ctx.loading, false);
  assert.equal(ctx.items[2].id, "c");
  assert.deepEqual(painted, ["pending slot filled"]);
  assert.equal(ctx.$g("gallery-full").src, "v1/images/files/c.png");
});
