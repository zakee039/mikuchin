import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

const sessionSource=readFileSync(new URL('../sessions.js',import.meta.url),'utf8');

test('native session actions offer only list pin, rename, export and delete',()=>{
  assert.match(sessionSource,/\["pin", item\.pinned \? "Unpin" : "Pin"\]/);
  assert.match(sessionSource,/\["rename", "Rename"\]/);
  assert.match(sessionSource,/\["export", "Export Markdown"\]/);
  assert.match(sessionSource,/\["delete", "Delete"\]/);
  assert.doesNotMatch(sessionSource,/Lock current model KV|Release current model KV|lock_kv|kv_locked|kv_cached/);
});

test('native session delete text cannot promise deletion of unported gallery assets',()=>{
  assert.match(sessionSource,/Delete this conversation and its saved messages permanently/);
  assert.doesNotMatch(sessionSource,/Delete conversation, generated chat images/);
});
