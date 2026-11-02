import zh from '../../locales/zh-CN.json';
import ja from '../../locales/ja-JP.json';
import en from '../../locales/en-US.json';
export type Language = 'zh-CN'|'ja-JP'|'en-US';
const supported=['zh-CN','ja-JP','en-US'];
const dictionaries:Record<string,Record<string,string>>={'zh-CN':zh,'ja-JP':ja,'en-US':en};
let language='zh-CN';
const originalText=new WeakMap<Text,{original:string,rendered:string}>();
const ignored='code,pre,textarea,input,[contenteditable],.model-text b,.model-text small,.detail-row strong,.figure';
export function getLocale(){return language;}
export function tr(value:string){return dictionaries[language]?.[value]||value;}
export function setLocale(value:string){if(supported.includes(value))language=value;document.documentElement.lang=language;translateDom(document.body);}
export function translateDom(node:Node):void{
  if(node.nodeType===Node.TEXT_NODE){
    const text=node as Text; if(!text.parentElement||text.parentElement.closest(ignored))return;
    const last=originalText.get(text);
    if(!last||(text.data!==last.original&&text.data!==last.rendered))
      originalText.set(text,{original:text.data,rendered:text.data});
    const record=originalText.get(text)!;
    const next=record.original.replace(/^(\s*)(.*?)(\s*)$/s,(_all,a:string,b:string,c:string)=>a+tr(b)+c);
    record.rendered=next;
    if(next!==text.data)text.data=next;
    return;
  }
  if(node.nodeType!==Node.ELEMENT_NODE)return;
  const element=node as HTMLElement;if(element.matches(ignored))return;
  for(const attr of ['title','placeholder','aria-label']){
    if(!element.hasAttribute(attr))continue;
    const k='mk'+attr.replace(/[^a-z]/g,'');
    const data=element.dataset as Record<string,string>;
    const from=data[k]??element.getAttribute(attr)??'';data[k]=from;
    const next=tr(from);if(element.getAttribute(attr)!==next)element.setAttribute(attr,next);
  }
  for(const child of element.childNodes)translateDom(child);
}
let observer:MutationObserver|null=null;
export function observeLocale(){if(observer)return;observer=new MutationObserver(records=>{
  for(const rec of records){if(rec.type==='characterData')translateDom(rec.target);
    else rec.addedNodes.forEach(translateDom);}
});observer.observe(document.body,{childList:true,characterData:true,subtree:true});}
