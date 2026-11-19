import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../image-studio.js", import.meta.url), "utf8");
const begin = source.indexOf("  function formatDuration(ms) {");
const end = source.indexOf("  // One server-side task equals one compact row;", begin);
assert.ok(begin >= 0 && end > begin, "extract actual production timer functions");

function createHarness() {
  const taskRecords = new Map();
  const taskRows = new Map();
  const ctx = {
    taskRecords, taskRows,
    activeJob: job => ["running", "submitting"].includes(job.state),
  };
  vm.createContext(ctx);
  vm.runInContext(source.slice(begin, end), ctx);
  return ctx;
}

function createRow() {
  const clock = {textContent: ""};
  const row = {isConnected: true, querySelector: selector =>
    selector === ".img-job-timer" ? clock : null};
  return {row,clock};
}

test("each running task has an independent wall-clock timer", () => {
  const ctx = createHarness();
  const time = 2_000_000;
  const a = createRow(), b = createRow();
  ctx.taskRecords.set("a", {state:"running",created:(time - 900000)/1000,started_at:(time - 65000)/1000});
  ctx.taskRecords.set("b", {state:"running",created:(time - 1000000)/1000,started_at:(time - 375000)/1000});
  ctx.taskRows.set("a",a.row);
  ctx.taskRows.set("b",b.row);
  ctx.tickTaskTimers(time);
  assert.equal(a.clock.textContent,"已运行 00:01:05");
  assert.equal(b.clock.textContent,"已运行 00:06:15");
  // Network polling can fail or stall; the display still updates on every tick.
  ctx.tickTaskTimers(time + 13000);
  assert.equal(a.clock.textContent,"已运行 00:01:18");
  assert.equal(b.clock.textContent,"已运行 00:06:28");
});

test("terminal and draft records stop counting; hidden rows are not modified", () => {
  const ctx = createHarness();
  const time = 3_000_000;
  const finished = createRow(), draft = createRow(), hidden = createRow();
  ctx.taskRecords.set("finished", {state:"success",created:(time-900000)/1000,started_at:(time-120000)/1000,finished_at:(time-60000)/1000,updated:(time-10000)/1000});
  ctx.taskRecords.set("draft", {state:"draft",created:(time-200000)/1000});
  ctx.taskRecords.set("hidden", {state:"running",created:(time-250000)/1000,started_at:(time-200000)/1000});
  ctx.taskRows.set("finished",finished.row);
  ctx.taskRows.set("draft",draft.row);
  hidden.row.isConnected = false;
  ctx.taskRows.set("hidden",hidden.row);
  ctx.tickTaskTimers(time);
  assert.equal(finished.clock.textContent, "");
  assert.equal(draft.clock.textContent, "");
  assert.equal(hidden.clock.textContent, "");
  assert.equal(ctx.taskElapsed(ctx.taskRecords.get("finished"), time+500000),"00:01:00");
  assert.equal(ctx.taskElapsed(ctx.taskRecords.get("draft"), time),"");
});

test("a reopened tab resumes from saved creation time rather than a local counter", () => {
  const ctx=createHarness();
  const row=createRow();
  const task={state:"running",created:1719990000,started_at:1720000000,updated:1720000100};
  ctx.taskRows.set("persistent",row.row);
  ctx.taskRecords.set("persistent",task);
  ctx.tickTaskTimers(1720003600*1000);
  assert.equal(row.clock.textContent,"已运行 01:00:00");
});


test("draft edits never start the clock and legacy tasks do not invent a start time", () => {
  const ctx=createHarness();
  assert.equal(ctx.taskElapsed({state:"draft",created:10,updated:900}, 2000000), "");
  assert.equal(ctx.taskElapsed({state:"running",created:10,updated:800}, 2000000), "");
  assert.equal(ctx.taskElapsed({state:"failed",created:10,updated:800}, 2000000), "");
  const failed={state:"failed",created:10,started_at:15,finished_at:20,updated:5000};
  assert.equal(ctx.taskElapsed(failed, 9000000), "00:00:05", "subsequent edits/updates must not change a finished job clock");
});
