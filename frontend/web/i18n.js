/* Mikuchin global UI language. Only UI chrome is translated; never alter messages or model text. */
"use strict";
(() => {
  const langs = window.MIKUCHIN_TRANSLATIONS || {};
  const localeSelect = document.getElementById('ui-language');
  let active = 'zh-CN';
  const source = new WeakMap();
  const ignored = '#chat, #session-history, .msg-content, .message, .lore-entry-body, pre, code, script, style, textarea, [contenteditable], [data-i18n-ignore]';
  const supported = ['zh-CN','ja-JP','en-US'];
  function currentTranslation(text) {return (langs[active] || {})[text] ?? text;}
  function transform(root) {
    if (!root || !root.isConnected) return;
    if (root.nodeType === Node.TEXT_NODE) {
      const parent = root.parentElement;
      if (!parent || parent.closest(ignored)) return;
      const last = source.get(root);
      if (!last || (root.nodeValue !== last.original && root.nodeValue !== last.rendered)) {
        source.set(root, {original:root.nodeValue,rendered:root.nodeValue});
      }
      const value = source.get(root);
      const next = value.original.replace(/^(\s*)(.*?)(\s*)$/s, (full,a,b,c) => a + currentTranslation(b) + c);
      value.rendered = next;
      if (root.nodeValue !== next) root.nodeValue = next;
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    if (root.matches(ignored)) return;
    if (root.hasAttribute('placeholder')) {
      const base = root.dataset.mkPlaceholder || root.getAttribute('placeholder');
      root.dataset.mkPlaceholder = base;
      const next = currentTranslation(base);
      if (next !== root.getAttribute('placeholder')) root.setAttribute('placeholder',next);
    }
    if (root.hasAttribute('title') && !root.matches('[data-copy]')) {
      const base = root.dataset.mkTitle || root.title;
      root.dataset.mkTitle = base;
      const next = currentTranslation(base);
      if (next !== root.title) root.title = next;
    }
    for(const child of root.childNodes) transform(child);
  }
  function apply(language) {
    active = supported.includes(language) ? language : 'zh-CN';
    document.documentElement.lang = active;
    if (localeSelect) localeSelect.value = active;
    transform(document.body);
    document.dispatchEvent(new CustomEvent('mikuchin-language-changed',{detail:{language:active}}));
  }
  async function refresh() {
    try {
      const response = await fetch('/v1/mikuchin/ui-language',{cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      if (supported.includes(data.language) && active !== data.language) apply(data.language);
    } catch (_) { /* standalone PolyStrata or server offline */ }
  }
  if (localeSelect) localeSelect.addEventListener('change',async () => {
    const next=localeSelect.value, previous=active;
    apply(next);
    try {
      const response=await fetch('/v1/mikuchin/ui-language',{
        method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({language:next})});
      if (!response.ok) throw new Error('HTTP '+response.status);
    } catch(err) {
      apply(previous);
      if (typeof toast === 'function') toast('error','Language change failed',String(err));
    }
  });
  const observer=new MutationObserver(records=>{
    for(const record of records){
      if(record.type==='characterData')transform(record.target);
      else for(const node of record.addedNodes)transform(node);
    }
  });
  apply('zh-CN');
  observer.observe(document.body,{childList:true,characterData:true,subtree:true});
  void refresh();setInterval(()=>void refresh(),5000);
  window.MikuchinI18n={apply,refresh,get language(){return active;},translate:currentTranslation};
})();
