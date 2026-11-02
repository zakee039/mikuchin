/* Native <select> remains the canonical form value; the menu is a custom, keyboard-accessible overlay. */
"use strict";
(() => {
  const targets='#card-list,#model-select,#img-size,#img-upscale,.source-kind';
  const widgets=new WeakMap();
  let opened=null;
  const close=()=>{if(opened){opened.menu.remove();opened.button.setAttribute('aria-expanded','false');opened=null;}};
  function make(select) {
    if(widgets.has(select)||!select.isConnected)return;
    const wrap=document.createElement('span');wrap.className='mk-dropdown';
    select.parentNode.insertBefore(wrap,select);
    wrap.appendChild(select);select.classList.add('mk-native-select');
    const button=document.createElement('button');button.type='button';button.className='mk-dropdown-button';
    button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
    const label=document.createElement('span');label.className='mk-dropdown-label';
    const arrow=document.createElement('span');arrow.className='mk-dropdown-arrow';arrow.textContent='⌄';
    button.append(label,arrow);wrap.appendChild(button);
    function sync(){const opt=select.selectedOptions[0];label.textContent=opt?.textContent||'—';button.disabled=select.disabled;wrap.hidden=select.hidden;}
    function show(){
      if(button.disabled)return;
      if(opened?.button===button){close();return;}close();
      const menu=document.createElement('div');menu.className='mk-dropdown-menu';menu.setAttribute('role','listbox');
      const options=[...select.options];
      options.forEach((option,index)=>{
        const item=document.createElement('button');item.type='button';item.className='mk-dropdown-item';
        item.setAttribute('role','option');item.setAttribute('aria-selected',String(index===select.selectedIndex));
        item.disabled=option.disabled;item.textContent=option.textContent;
        if(index===select.selectedIndex)item.classList.add('selected');
        item.onclick=()=>{select.selectedIndex=index;select.dispatchEvent(new Event('change',{bubbles:true}));sync();close();button.focus();};
        menu.appendChild(item);
      });
      document.body.append(menu);
      const rect=button.getBoundingClientRect();const height=Math.min(300,Math.max(80,window.innerHeight-16));
      const below=window.innerHeight-rect.bottom>=Math.min(250,options.length*38+12);
      const top=below?rect.bottom+4:Math.max(8,rect.top-Math.min(menu.scrollHeight,height)-4);
      menu.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-rect.width-8))+'px';
      menu.style.top=top+'px';menu.style.minWidth=rect.width+'px';menu.style.maxWidth='min(360px,calc(100vw - 16px))';
      opened={menu,button};button.setAttribute('aria-expanded','true');
      menu.querySelector('.selected')?.scrollIntoView({block:'nearest'});
    }
    button.onclick=show;
    button.onkeydown=e=>{
      if(e.key==='Escape'){close();return;}
      if(e.key==='ArrowDown'||e.key==='ArrowUp'||e.key==='Enter'||e.key===' '){
        if(!opened)show();
        const items=[...opened.menu.querySelectorAll('.mk-dropdown-item:not([disabled])')];
        const now=items.indexOf(document.activeElement);
        if(e.key==='ArrowDown'||e.key==='ArrowUp')items[(now+(e.key==='ArrowDown'?1:items.length-1)+items.length)%items.length]?.focus();
        else if(now>=0)items[now].click();
        e.preventDefault();
      }
    };
    select.addEventListener('change',sync);
    new MutationObserver(sync).observe(select,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','hidden','label']});
    widgets.set(select,{sync,button});sync();
  }
  document.addEventListener('click',e=>{if(opened&&!opened.menu.contains(e.target)&&!opened.button.contains(e.target))close();},true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
  document.addEventListener('scroll',close,true);
  document.addEventListener('mikuchin-language-changed',()=>{close();document.querySelectorAll(targets).forEach(el=>widgets.get(el)?.sync());});
  function scan(root=document){if(root.matches?.(targets))make(root);root.querySelectorAll?.(targets).forEach(make);}
  scan();new MutationObserver(list=>list.forEach(rec=>rec.addedNodes.forEach(n=>{if(n.nodeType===1)scan(n);}))).observe(document.body,{childList:true,subtree:true});
})();
