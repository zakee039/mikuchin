import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";

const source=readFileSync(new URL("../image-studio.js",import.meta.url),"utf8");
function block(a,b) {
  const first=source.indexOf(a), last=source.indexOf(b, first);
  assert.ok(first>=0 && last>first,`missing code block: ${a}`);
  return source.slice(first,last);
}

const actionCode=block("  function updateTaskActions(row, job) {", "  function renderTaskRows() {");
const editCode=block("  async function editTask(job) {", "  async function copyTaskError(");

function harness() {
  const calls=[], copied=[];
  const context={
    calls,copied,
    taskRecords:new Map(),
    draftTimer:null,
    draftWrites:Promise.resolve(),
    activeJob:job=>job.state==="running",
    flushDraftSave:async()=>{calls.push(["flush"]);},
    jobCommand:async body=>{
      calls.push(["api",body]);
      return {id:"new-task", state:body.action==="retry"?"running":"draft",
        ...(body.action==="retry" && context.taskRecords.get(body.id)?.state==="failed" ?
          {deleted_original_id:body.id} : {}), request:{prompt:"hello"}};
    },
    loadTaskForm:async data=>{calls.push(["load-form",data.id]);},
    renderTaskRows:()=>calls.push(["render"]),
    refreshImageJobs:async()=>{},
    toast:(...parts)=>calls.push(["toast",...parts]),
    taskAction:(label,handler)=>({label,handler}),
    changeTaskRecords:async()=>{},
    copyTaskError:async()=>{},
    confirm:()=>false,
  };
  vm.createContext(context);
  vm.runInContext(editCode+actionCode,context);
  return context;
}

test("Edit appears for all four states, retry only on success/failed",()=>{
  const ctx=harness();
  for(const state of ["draft","running","success","failed"]) {
    const actions={dataset:{},children:[],replaceChildren(){this.children=[];},append(...parts){this.children.push(...parts);}};
    const row={querySelector:()=>actions};
    ctx.updateTaskActions(row,{id:"source",state,error:state==="failed"?"timeout":""});
    const labels=actions.children.map(button=>button.label);
    assert.ok(labels.includes("编辑"),state);
    assert.equal(labels.includes("重试"),state==="success"||state==="failed",state);
  }
});

test("editing a draft touches the same ID; other states copy to a new ID",async()=>{
  for(const state of ["draft","running","success","failed"]) {
    const ctx=harness();
    await ctx.editTask({id:"source",state});
    const input=ctx.calls.find(record=>record[0]==="api")?.[1];
    assert.equal(input.action,"draft");
    if(state==="draft") {
      assert.equal(input.id,"source");
      assert.equal(input.copy_id,undefined);
    } else {
      assert.equal(input.copy_id,"source");
      assert.equal(input.id,undefined);
    }
    assert.deepEqual(ctx.calls.find(record=>record[0]==="load-form"),["load-form","new-task"]);
  }
});

test("retry makes a new running task without loading the editing form",async()=>{
  const ctx=harness();
  ctx.taskRecords.set("source", {id:"source",state:"success"});
  await ctx.retryTask({id:"source",state:"success"});
  assert.equal(ctx.calls.find(record=>record[0]==="api")?.[1].action,"retry");
  assert.equal(ctx.calls.find(record=>record[0]==="api")?.[1].id,"source");
  assert.equal(ctx.calls.some(record=>record[0]==="load-form"),false);
  assert.equal(ctx.taskRecords.get("new-task")?.state,"running");
  assert.equal(ctx.taskRecords.get("source")?.state,"success");
});

test("retrying a failed job destroys the failed row only after submission succeeds",async()=>{
  const ctx=harness();
  const failed={id:"source",state:"failed",error:"timeout"};
  ctx.taskRecords.set("source", failed);
  ctx.taskRows=new Map([["source",{node:true}]]);
  await ctx.retryTask(failed);
  assert.equal(ctx.taskRecords.has("source"),false);
  assert.equal(ctx.taskRows.has("source"),false);
  assert.equal(ctx.taskRecords.get("new-task")?.state,"running");
  assert.ok(ctx.calls.some(entry=>entry[0]==="toast"&&entry.join(" ").includes("原失败任务记录已删除")));
});

test("failed submission does not delete a failed source or show success",async()=>{
  const ctx=harness();
  const failed={id:"source",state:"failed"};
  ctx.taskRecords.set("source", failed);
  ctx.jobCommand=async()=>{throw new Error("queue full")};
  await ctx.retryTask(failed);
  assert.equal(ctx.taskRecords.get("source"),failed);
  assert.equal(ctx.taskRecords.has("new-task"),false);
  assert.ok(ctx.calls.some(entry=>entry[0]==="toast"&&entry[1]==="error"));
});

test("failed tasks use a persistent collapsed details element rather than the phase row",()=>{
 assert.match(source,/part\("details", "img-job-error-details"\)/);
 assert.match(source,/phase\.hidden = failed/);
 assert.match(source,/errorDetails\.hidden = !failed/);
 const ctx=harness();
 assert.equal(ctx.taskErrorText("ImageProviderError: API 网络超时，阶段 request_sent，路线 proxy"),"ImageProviderError: API 网络超时，阶段 request_sent，路线 proxy");
 assert.match(ctx.taskErrorText('HTTP 400: {"prompt":"private","referenced_image_ids":["file_private"]}'),/file_private|"prompt"/);
});
