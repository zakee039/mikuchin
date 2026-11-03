"""Chat-local sampling is persisted on the server, never per-browser."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'frontend/web/app.js').read_text(encoding='utf8')
POLY=ROOT/'backend/polystrata'
sys.path.insert(0,str(POLY))

class SamplingPolicy(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node required')
    def test_ui_budget_mapping_and_custom_override(self):
        a=JS.index('const THINKING_BUDGET_TOKENS')
        b=JS.index('const OLD_DEFAULT_TEMPERATURE',a)
        code = JS[a:b] + """
const cases=['none','low','medium','high'].map(thinking => {
  const settings={...DEFAULTS,thinking,budget:THINKING_BUDGET_TOKENS[thinking]};
  return [thinking,thinkingBudget(settings)];
});
const custom=thinkingBudget({...DEFAULTS,budget:3072});
console.log(JSON.stringify({cases,custom}));
"""

        r=subprocess.run(['node','-e',code],text=True,capture_output=True,cwd=ROOT,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads(r.stdout)
        self.assertEqual(dict(result['cases']),{'none':0,'low':1024,'medium':4096,'high':16388})
        self.assertEqual(result['custom'],3072)
    def test_no_browser_sampling_or_cross_app_sync(self):
        self.assertIn('let settings = {...DEFAULTS};',JS)
        self.assertIn('settings = {...DEFAULTS, ...(saved.sampling || {})};',JS)
        self.assertIn('settings = {...DEFAULTS};',JS)
        self.assertIn('action: "sampling", sampling: next',JS)
        self.assertIn('await refreshCurrentSampling();',JS)
        self.assertIn('reasoning_budget_tokens: thinkingBudget(settings)',JS)
        self.assertNotIn('store.set("sampling",',JS)
        self.assertNotIn('store.get("sampling",',JS)
        self.assertNotIn('loadShared()',JS)
        self.assertNotIn('sharedDefaults(',JS)
        html=(ROOT/'frontend/web/index.html').read_text('utf8')
        self.assertIn('id="s-budget"',html)
        self.assertNotIn('id="s-share"',html)
    def test_character_stable_prefix_precedes_workflow(self):
        character = (ROOT/'frontend/web/characters.js').read_text('utf8')
        start = character.index('async function characterPrompt(')
        end = character.index('window.polyCharacterPrompt = characterPrompt;',start)
        prompt = character[start:end]
        self.assertLess(prompt.index('for (const entry of [...(card.lorebook'),
                        prompt.index('if (card.workflow_path && sessionV1 && sessionId)'))
        self.assertLess(prompt.index('const retrieval = await characterRequest("retrieve"'),
                        prompt.index('if (card.workflow_path && sessionV1 && sessionId)'))
    def test_service_has_no_separate_budget(self):
        from serve.server import model_settings
        self.assertEqual(model_settings({})['reasoning_budget_tokens'],0)
        p=ROOT/'config/active.json'
        if p.exists():self.assertNotIn('reasoning_budget_tokens',json.loads(p.read_text('utf8')))

if __name__=='__main__':unittest.main()
