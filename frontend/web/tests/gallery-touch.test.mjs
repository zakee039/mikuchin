import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";

// Exercise the real gallery pointer handlers without loading photos or
// depending on browser/CDP, so even private/NSFW images stay untouched.
const source = readFileSync(new URL("../gallery.js", import.meta.url), "utf8");
const start = source.indexOf('  const wrap=$g("gallery-viewer-wrap");');
const endToken = '  wrap.addEventListener("pointercancel",endPointer);';
const end = source.indexOf(endToken, start);
assert.ok(start >= 0 && end > start, "gallery gesture handlers are present");
const handlersSource = source.slice(start, end + endToken.length);

function setup() {
  const listeners = new Map();
  const captures = [];
  const shifts = [];
  const wrap = {
    addEventListener(name, callback) {listeners.set(name, callback);},
    setPointerCapture(id) {captures.push(id);},
  };
  const ctx = {
    $g(id) {return id === "gallery-viewer-wrap" ? wrap : {hidden: false};},
    fingers: new Map(),
    zoom: 1, panX: 0, panY: 0,
    pinch: null, dragStart: null, lastTap: null, tapTimer: null,
    chromeVisible: true, setChrome() {},
    shift(delta) {shifts.push(delta);},
    setZoom() {}, clampPan() {}, applyZoom() {},
    setTimeout() {return 1;}, clearTimeout() {},
    Math, Date,
  };
  vm.runInNewContext(handlersSource, ctx, {filename:"gallery.js gestures"});
  function pointer(type, id, x, y, button = false) {
    const event = {
      pointerId: id, clientX: x, clientY: y,
      target: {closest(selector) {assert.equal(selector, "button"); return button ? {} : null;}},
      preventDefault() {event.prevented = true;},
    };
    listeners.get(type)(event);
    return event;
  }
  return {ctx, captures, shifts, pointer};
}

test("swiping a covered NSFW artwork navigates without revealing it", () => {
  const {ctx, captures, shifts, pointer} = setup();
  const started = pointer("pointerdown", 11, 240, 400);
  assert.equal(started.prevented, true);
  assert.deepEqual(captures, [11]);
  pointer("pointermove", 11, 80, 400);
  pointer("pointerup", 11, 80, 400);
  assert.deepEqual(shifts, [1]);
  assert.equal(ctx.fingers.size, 0);
});

test("the explicit NSFW reveal button still receives its click", () => {
  const {captures, shifts, pointer} = setup();
  const started = pointer("pointerdown", 12, 240, 400, true);
  assert.equal(started.prevented, undefined);
  pointer("pointermove", 12, 80, 400, true);
  pointer("pointerup", 12, 80, 400, true);
  assert.deepEqual(captures, []);
  assert.deepEqual(shifts, []);
});
