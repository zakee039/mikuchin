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
      return {id:"new-task", state:body.action==="retry"?"running":"draft", request:{prompt:"hello"}};
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
  await ctx.retryTask({id:"source",state:"success"});
  assert.equal(ctx.calls.find(record=>record[0]==="api")?.[1].action,"retry");
  assert.equal(ctx.calls.find(record=>record[0]==="api")?.[1].id,"source");
  assert.equal(ctx.calls.some(record=>record[0]==="load-form"),false);
  assert.equal(ctx.taskRecords.get("new-task")?.state,"running");
});
