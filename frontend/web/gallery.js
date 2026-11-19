// Mikuchin unified image gallery — index-backed, no direct filesystem access.
"use strict";
(() => {
  const $g = id => document.getElementById(id);
  const api = "v1/mikuchin/gallery";
  const secure = window.MikuchinSecureImages;
  const translate = value => window.MikuchinI18n?.translate(value) || value;
  const limit = 60;
  let items = [], total = 0, loading = false, multi = false;
  let selected = new Set(), lightbox = -1, revealed = false;
  let visibleNsfw = false, fetchVersion = 0;
  let variant = "upscaled", zoom = 1, panX = 0, panY = 0;
  const fingers = new Map();
  const upscaleJobs = new Map();
  let pinch = null, dragStart = null, lastTap = null, chromeVisible = true;
  const appliedUpscales = new Set();
  let pollingUpscales = false, tapTimer = null;
  let expectedFullSrc = "", preloadTimer = null;
  const neighborPreloads = new Map();

  function fullSrc(item, selectedVariant = "upscaled") {
    if (!item) return "";
    const pair = Boolean(item.variants?.original && item.variants?.upscaled);
    const imageId = pair && selectedVariant === "original" ? item.variants.original : item.id;
    return "v1/images/files/" + imageId + ".png";
  }

  // Only the two immediate neighbors receive full-resolution preloads. Never
  // compete with the foreground image fetch, and bound decoded-image memory.
  function prefetchNeighbors() {
    if (preloadTimer != null) clearTimeout(preloadTimer);
    preloadTimer = setTimeout(() => {
      preloadTimer = null;
      if (lightbox < 0 || lightbox >= items.length) return;
      const urls = new Set();
      for (const offset of [-1, 1]) {
        const index = (lightbox + offset + items.length) % items.length;
        if (index === lightbox) continue;
        const url = fullSrc(items[index]);
        if (url) urls.add(url);
      }
      for (const [url] of neighborPreloads) {
        if (!urls.has(url)) neighborPreloads.delete(url);
      }
      for (const url of urls) {
        if (neighborPreloads.has(url)) continue;
        neighborPreloads.set(url, true);
        void secure.prefetch(url).catch(() => neighborPreloads.delete(url));
      }
      // Warm the next metadata page before the user reaches its boundary.
      if (items.length < total && lightbox >= items.length - 3 && !loading) {
        void load(false);
      }
    }, 160);
  }

  const sourceLabel = value => ({
    studio:"生图",chat:"聊天",local:"本地",api:"API"
  })[value] || value || "—";
  const dateLabel = seconds => {
    const n = Number(seconds);
    if (!Number.isFinite(n) || !n) return "—";
    try {return new Date(n * 1000).toLocaleString(document.documentElement.lang || "zh-CN", {
      year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"
    });} catch {return "—";}
  };
  async function request(body) {
    const options = {headers:headers(Boolean(body)),cache:"no-store"};
    if (body) {options.method="POST";options.body=JSON.stringify(body);}
    const response = await fetch(api,options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(result.error?.message || "HTTP " + response.status);
    return result;
  }
  const masked = item => Boolean(item?.nsfw && !visibleNsfw);
  function make(tag, cls, value) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value != null) node.textContent = value;
    return node;
  }
  function setSelectionUI() {
    $g("gallery-selection-bar").hidden = !multi;
    $g("gallery-select-mode").textContent = multi ? "完成" : "选择";
    $g("gallery-selected-count").textContent = "已选择 " + selected.size + " 张";
    $g("gallery-delete-selected").disabled = !selected.size;
    $g("gallery-batch-nsfw").disabled = !selected.size;
    $g("gallery-delete-selected").textContent = selected.size ? "删除所选 (" + selected.size + ")" : "删除所选";
  }
  function render() {
    const grid = $g("gallery-grid");
    secure.clearWithin(grid);
    grid.replaceChildren();
    $g("gallery-count").textContent = total + " 张";
    $g("gallery-empty").hidden = Boolean(items.length || loading);
    $g("gallery-more").hidden = items.length >= total || !items.length;
    for (const [index, item] of items.entries()) {
      const active = selected.has(item.id);
      const card = make("button","gallery-card" + (active?" gallery-selected":"") + (multi?" is-selecting":""));
      card.type="button";
      card.dataset.galleryId=item.id;
      card.setAttribute("aria-label", "查看生成图片 " + (item.model || item.id));
      card.setAttribute("aria-pressed", String(multi && active));
      const frame = make("div","gallery-card-media");
      const img = make("img",masked(item)?"gallery-blurred":"");
      void secure.load(img,api + "/thumb/" + item.id).catch(() => {
        img.alt = "缩略图需要鉴权，无法加载";
      });
      img.loading = index < 12 ? "eager" : "lazy";
      img.decoding = "async";
      img.alt = item.model || "生成图片";
      frame.append(img);
      if (item.nsfw && masked(item)) {
        const shade = make("div","gallery-spoiler");
        shade.append(make("span","", "NSFW · 已隐藏"));
        frame.append(shade);
      }
      if (multi) frame.append(make("span","gallery-select-mark",active ? "✓" : ""));
      if ((item.variant_count || 1) > 1) {
        const badge=make("span","gallery-pair-badge",String(item.variant_count));
        badge.title="原图和 4× 超分图，共 " + item.variant_count + " 张";
        frame.append(badge);
      }
      frame.append(make("span","gallery-source-label",sourceLabel(item.source)));
      const desc = make("div","gallery-card-meta");
      desc.append(make("strong","", item.model || "历史生成图片"));
      desc.append(make("span","", dateLabel(item.created) + " · " + item.width + "×" + item.height));
      card.append(frame, desc);
      card.addEventListener("click", () => multi ? toggle(item.id) : open(index));
      grid.append(card);
    }
    setSelectionUI();
  }
  function toggle(id) {
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    render();
  }
  async function load(reset = true) {
    if (loading) return;
    loading=true;
    const version=++fetchVersion;
    if (reset) {
      items=[];total=0;selected.clear();
      if (lightbox !== -1) close();
    }
    const previousLength = items.length;
    $g("gallery-empty").hidden=true;
    $g("gallery-more").disabled=true;
    try {
      const query = new URLSearchParams({
        source:$g("gallery-source").value,
        order:$g("gallery-order").value,
        limit:String(limit),offset:String(items.length)
      });
      const response = await fetch(api+"?"+query.toString(),
        {headers:headers(),cache:"no-store"});
      const answer = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(answer.error?.message || "HTTP "+response.status);
      if (fetchVersion !== version) return;
      const wasWaitingForPage = lightbox >= items.length && lightbox !== -1;
      total=answer.total || 0;
      items.push(...(Array.isArray(answer.items)?answer.items:[]));
      // A newly requested page belongs behind the overlay. Avoid rebuilding
      // the entire thumbnail grid on the critical swipe-to-paint path.
      if (lightbox === -1) render();
      else {
        $g("gallery-count").textContent = total + " 张";
        $g("gallery-more").hidden = items.length >= total;
      }
      if (wasWaitingForPage && lightbox < items.length) showViewer();
      else if (!wasWaitingForPage && lightbox >= 0 && items.length > previousLength) prefetchNeighbors();
      else if (wasWaitingForPage && items.length === previousLength) {
        $g("gallery-image-loading").textContent="暂时无法加载下一页，请向左滑返回";
      }
    } catch(e) {
      toast("error","画廊加载失败",String(e.message||e),6000);
      if (!items.length) $g("gallery-empty").textContent = "画廊加载失败，请检查服务连接";
      $g("gallery-empty").hidden=Boolean(items.length);
      if (lightbox >= items.length && lightbox !== -1) {
        $g("gallery-image-loading").textContent="加载失败，请返回上一张重试";
      }
    } finally {
      loading=false;
      $g("gallery-more").disabled=false;
      $g("gallery-more").hidden = items.length >= total;
      // Rapid gestures may have queued an index beyond one page. Keep
      // fetching in the background rather than blocking those gestures.
      if (lightbox >= items.length && lightbox < total && items.length > previousLength) {
        setTimeout(() => {if (lightbox >= items.length && !loading) void load(false);},0);
      }
    }
  }
  function open(index) {
    if (!items[index]) return;
    lightbox=index;revealed=false;variant="upscaled";
    resetZoom();chromeVisible=true;setChrome(true);
    $g("gallery-viewer").hidden=false;
    showViewer();
    void checkUpscaleJobs();
    // Viewing follows the phone's current orientation; no automatic rotation.
    $g("gallery-close").focus();
  }
  function close() {
    if (lightbox === -1) return;
    const id=items[lightbox]?.id;
    lightbox=-1;revealed=false;
    expectedFullSrc="";
    if (preloadTimer != null) {clearTimeout(preloadTimer);preloadTimer=null;}
    neighborPreloads.clear();
    $g("gallery-viewer").hidden=true;
    resetZoom();
    if (document.fullscreenElement===$g("gallery-viewer"))
      void document.exitFullscreen().catch(() => {});
    secure.release($g("gallery-full"));
    $g("gallery-preview").hidden=true;
    secure.release($g("gallery-preview"));
    $g("gallery-image-loading").hidden=true;
    render();
    const from=$g("gallery-grid").querySelector('[data-gallery-id="'+id+'"]');
    from?.focus({preventScroll:true});
  }
  function showViewer() {
    if (lightbox === -1) return;
    const item=items[lightbox];
    $g("gallery-position").textContent=(lightbox+1)+" / "+total;
    if (!item) {
      // The user has already navigated to a not-yet-fetched page. Paint its
      // place immediately; network metadata and pixels arrive independently.
      expectedFullSrc="";
      $g("gallery-full").classList.add("gallery-full-loading");
      secure.release($g("gallery-full"));
      $g("gallery-preview").hidden=true;
      secure.release($g("gallery-preview"));
      $g("gallery-image-loading").textContent="正在获取下一张…";
      $g("gallery-image-loading").hidden=false;
      $g("gallery-viewer-spoiler").hidden=true;
      $g("gallery-variant-picker").hidden=true;
      $g("gallery-create-upscale").hidden=true;
      $g("gallery-delete-original").hidden=true;
      $g("gallery-delete-upscaled").hidden=true;
      $g("gallery-details").textContent="正在加载图片信息…";
      $g("gallery-prompt").textContent="";
      return;
    }
    const pair=Boolean(item.variants?.original && item.variants?.upscaled);
    if (!pair) variant="original";
    const nextSrc=fullSrc(item,variant);
    const full=$g("gallery-full"),preview=$g("gallery-preview");
    if (secure.path(full)!==nextSrc) {
      resetZoom();
      full.classList.add("gallery-full-loading");
      preview.hidden=false;
      void secure.load(preview,api+"/thumb/"+item.id).catch(() => {});
      expectedFullSrc=nextSrc;
      // Assign the requested full image *after* displaying its lightweight
      // preview, never wait for the file before updating the viewer state.
      void secure.load(full,nextSrc).then(accepted => {
        if (accepted && expectedFullSrc===nextSrc && full.complete && full.naturalWidth)
          finishFullImage();
      }).catch(() => {
        if (expectedFullSrc===nextSrc)
          $g("gallery-image-loading").textContent="图片加载失败，请检查鉴权";
      });
    }
    const hide=masked(item) && !revealed;
    $g("gallery-full").classList.toggle("gallery-blurred",hide);
    preview.classList.toggle("gallery-blurred",hide);
    $g("gallery-viewer-spoiler").hidden=!hide;
    if (full.complete && full.naturalWidth>0) finishFullImage();
    else {
      $g("gallery-image-loading").textContent="高清图片加载中…";
      $g("gallery-image-loading").hidden=false;
    }
    $g("gallery-mark-nsfw").textContent=item.nsfw?"取消 NSFW 标记":"标记为 NSFW";
    $g("gallery-variant-picker").hidden=!pair;
    $g("gallery-create-upscale").hidden=pair;
    $g("gallery-show-original").classList.toggle("active",variant==="original");
    $g("gallery-show-upscaled").classList.toggle("active",variant==="upscaled");
    $g("gallery-show-original").setAttribute("aria-pressed",String(variant==="original"));
    $g("gallery-show-upscaled").setAttribute("aria-pressed",String(variant==="upscaled"));
    const job=upscaleJobs.get(item.id);
    const pending=job && ["queued","working"].includes(job.state);
    const action=$g("gallery-create-upscale");
    action.disabled=true;
    action.hidden=true; // Native local upscaler has not been ported yet.
    action.textContent=translate("4x 需本地 Image Worker 支持");
    $g("gallery-delete-original").hidden=!pair;
    $g("gallery-delete-upscaled").hidden=!pair;
    $g("gallery-details").textContent=[
      dateLabel(item.created),sourceLabel(item.source),
      item.provider?sourceLabel(item.provider):"",
      item.model,item.width+"×"+item.height,
      (item.variant_count || 1)>1?"原图 + 4× 超分":""
    ].filter(Boolean).join(" · ");
    $g("gallery-prompt").textContent=item.prompt || "";
  }
  function finishFullImage() {
    const full=$g("gallery-full");
    if (lightbox<0 || secure.path(full)!==expectedFullSrc || !full.naturalWidth) return;
    full.classList.remove("gallery-full-loading");
    $g("gallery-preview").hidden=true;
    $g("gallery-image-loading").hidden=true;
    clampPan();applyZoom();
    prefetchNeighbors();
  }
  function shift(delta) {
    if (lightbox === -1 || !items.length) return;
    const next=lightbox+delta;
    if (next>=total) lightbox=0;
    else if (next<0) lightbox=items.length-1;
    else lightbox=next;
    revealed=false;variant="upscaled";resetZoom();
    showViewer();
    if (lightbox>=items.length) {
      if (!loading) void load(false);
    }
  }
  function setChrome(visible) {
    chromeVisible=visible;
    $g("gallery-viewer").classList.toggle("gallery-chrome-hidden",!visible);
  }
  function applyZoom() {
    $g("gallery-full").style.transform=`translate(${panX}px, ${panY}px) scale(${zoom})`;
    $g("gallery-viewer-wrap").classList.toggle("is-zoomed",zoom>1.01);
  }
  function clampPan() {
    const img=$g("gallery-full"), rect=$g("gallery-viewer-wrap").getBoundingClientRect();
    if (!img.naturalWidth || !img.naturalHeight || !rect.width || !rect.height) return;
    const fit=Math.min(rect.width/img.naturalWidth,rect.height/img.naturalHeight);
    const maxX=Math.max(0,(img.naturalWidth*fit*zoom-rect.width)/2);
    const maxY=Math.max(0,(img.naturalHeight*fit*zoom-rect.height)/2);
    panX=Math.min(maxX,Math.max(-maxX,panX));
    panY=Math.min(maxY,Math.max(-maxY,panY));
  }
  function resetZoom() {
    zoom=1;panX=0;panY=0;pinch=null;dragStart=null;lastTap=null;
    if(tapTimer){clearTimeout(tapTimer);tapTimer=null;}
    fingers.clear();applyZoom();
  }
  function setZoom(level,x,y) {
    const next=Math.min(4,Math.max(1,level));
    const rect=$g("gallery-viewer-wrap").getBoundingClientRect();
    const cx=x-(rect.left+rect.width/2),cy=y-(rect.top+rect.height/2);
    panX=cx-(cx-panX)*next/zoom;
    panY=cy-(cy-panY)*next/zoom;
    zoom=next;
    if (zoom<=1.01) {zoom=1;panX=0;panY=0;}
    clampPan();applyZoom();
  }
  async function requestFullscreen() {
    const viewer=$g("gallery-viewer");
    try {
      if (!document.fullscreenElement && viewer.requestFullscreen) await viewer.requestFullscreen();
    } catch (_error) {
      // Unsupported browsers keep using the fixed viewer in the current orientation.
    }
  }
  async function updateUpscaledItem(sourceId) {
    if (appliedUpscales.has(sourceId)) return;
    const response=await fetch(api+"/item?id="+encodeURIComponent(sourceId),
      {headers:headers(),cache:"no-store"});
    if (!response.ok) throw Error("无法读取超分结果");
    const fresh=await response.json();
    appliedUpscales.add(sourceId);
    const index=items.findIndex(item=>item.id===sourceId||item.variants?.original===sourceId);
    if (index!==-1) {
      items[index]=fresh;
      render();
      if (lightbox===index) {variant="upscaled";showViewer();}
    }
  }
  async function checkUpscaleJobs() {
    if (lightbox===-1||pollingUpscales) return;
    pollingUpscales=true;
    try {
      const response=await fetch("v1/mikuchin/image-jobs", {headers:headers(),cache:"no-store"});
      if (!response.ok) return;
      const data=await response.json();
      for (const job of data.jobs||[]) {
        if (job.kind!=="upscale") continue;
        upscaleJobs.set(job.source_id,job);
        if (job.state==="done" && !appliedUpscales.has(job.source_id)) {
          try {await updateUpscaledItem(job.source_id);}catch(_error){}
        }
      }
      if (lightbox!==-1) showViewer();
    } catch (_error) { /* The desktop worker keeps running while the browser is offline. */ }
    finally {pollingUpscales=false;}
  }
  async function createUpscale() {
    const item=items[lightbox];
    if (!item || item.variants?.upscaled) return;
    const button=$g("gallery-create-upscale");
    button.disabled=true;
    try {
      const response=await fetch("v1/mikuchin/image-jobs",{
        method:"POST",headers:headers(true),cache:"no-store",
        body:JSON.stringify({kind:"upscale",image_id:item.id})});
      const job=await response.json().catch(()=>({}));
      if (!response.ok) throw Error(job.error?.message || "HTTP "+response.status);
      upscaleJobs.set(item.id,job);
      toast("success","已提交 4x 任务","桌面端会独立完成；可关闭浏览器或继续浏览图片。",5000);
    } catch (error) {
      toast("error","无法提交 4x 任务",String(error.message||error),6000);
    } finally {if(lightbox!==-1)showViewer();}
  }
  async function mutateNsfw() {
    const item=items[lightbox];
    if (!item) return;
    try {
      const result=await request({action:"nsfw",id:item.id,nsfw:!item.nsfw});
      item.nsfw=result.nsfw;
      revealed=false;
      render();
      showViewer();
    } catch(e) {toast("error","NSFW 标记失败",String(e.message||e));}
  }
  async function markSelectedNsfw() {
    const ids=[...selected];
    if (!ids.length) return;
    if (!confirm("将选中的 "+ids.length+" 组作品标记为 NSFW？原图和 4× 图片将同时生效。")) return;
    try {
      let updated=0;
      for(let i=0;i<ids.length;i+=150){
        const answer=await request({action:"nsfw_many",ids:ids.slice(i,i+150),nsfw:true});
        const changed=new Set(answer.updated || []);
        for (const item of items) if(changed.has(item.id)) item.nsfw=true;
        updated+=changed.size;
      }
      render();
      toast("success","已标记 NSFW","共 "+updated+" 组作品");
    } catch(e) {
      await load(true);
      toast("error","批量标记失败",String(e.message||e),6000);
    }
  }

  async function deleteSingleVariant(variant) {
    const item=items[lightbox];
    if(!item?.variants?.original || !item?.variants?.upscaled) return;
    const original=variant==="original";
    const name=original?"原图":"4× 超分图";
    if(!confirm("只删除这组作品的"+name+"？\n另一份图片将保留。"
      +(original?"":"\n聊天记录如果引用了 4× 图片，删除后该引用将失效。")
      +"\n此操作不可撤销。"))return;
    try {
      const result=await request({action:"delete_variant",id:item.id,variant});
      const remaining=result.remaining;
      await load(true);
      const found=items.findIndex(entry=>entry.id===remaining);
      if(found!==-1) open(found);
      toast("success","已删除"+name,"保留了另一份图片");
    }catch(e){
      toast("error","删除"+name+"失败",String(e.message||e),6000);
    }
  }

  async function deleteImages(ids) {
    const n=ids.length;
    if (!n) return;
    if (!confirm("永久删除选中的 "+n+" 组作品？\n每组的原图与 4× 超分图将一起删除，聊天记录中引用的图片也可能失效。此操作不可撤销。")) return;
    try {
      let removed=0,groups=0,failed=0;
      for(let i=0;i<ids.length;i+=150){
        const result=await request({action:"delete",ids:ids.slice(i,i+150)});
        removed+=(result.deleted?.length||0);
        groups+=(result.deleted_groups||0);
        failed+=(result.failed?.length||0);
      }
      if (failed) toast("warn","部分图片未删除","已删除 "+removed+" 个文件，失败 "+failed+" 个",5000);
      else toast("success","删除完成","已删除 "+groups+" 组作品，共 "+removed+" 个文件");
      secure.clearCache(); // A deleted image must not remain in the private byte cache.
      if (lightbox!==-1) close();
      selected.clear();
      await load(true);
    } catch(e) {toast("error","删除失败",String(e.message||e),6000);}
  }
  $g("gallery-select-mode").addEventListener("click",() => {
    multi=!multi;selected.clear();
    if (lightbox!==-1) close();
    render();
  });
  $g("gallery-select-all").addEventListener("click",()=> {
    for (const item of items) selected.add(item.id);
    render();
  });
  $g("gallery-select-none").addEventListener("click",()=> {selected.clear();render();});
  $g("gallery-delete-selected").addEventListener("click",()=>deleteImages([...selected]));
  $g("gallery-batch-nsfw").addEventListener("click",markSelectedNsfw);
  $g("gallery-source").addEventListener("change",()=>load(true));
  $g("gallery-order").addEventListener("change",()=>load(true));
  $g("gallery-show-nsfw").addEventListener("change",e=> {
    visibleNsfw=e.target.checked;render();if(lightbox!==-1)showViewer();
  });
  $g("gallery-refresh").addEventListener("click",async()=>{
    try {
      const scan=await request({action:"repair"});
      await load(true);
      if(scan.added||scan.removed)toast("success","索引已同步","补入 "+scan.added+" 张，清理 "+scan.removed+" 条");
    } catch(e){toast("error","刷新失败",String(e.message||e));}
  });
  $g("gallery-more").addEventListener("click",()=>load(false));
  $g("gallery-close").addEventListener("click",close);
  $g("gallery-create-upscale").addEventListener("click",()=>void createUpscale());
  $g("gallery-show-original").addEventListener("click",()=>{variant="original";showViewer();});
  $g("gallery-show-upscaled").addEventListener("click",()=>{variant="upscaled";showViewer();});
  $g("gallery-fullscreen").addEventListener("click",()=>void requestFullscreen());
  $g("gallery-prev").addEventListener("click",()=>shift(-1));
  $g("gallery-next").addEventListener("click",()=>shift(1));
  $g("gallery-mark-nsfw").addEventListener("click",mutateNsfw);
  $g("gallery-reveal").addEventListener("click",()=>{revealed=true;showViewer();});
  $g("gallery-delete-original").addEventListener("click",()=>deleteSingleVariant("original"));
  $g("gallery-delete-upscaled").addEventListener("click",()=>deleteSingleVariant("upscaled"));
  $g("gallery-viewer-delete").addEventListener("click",()=> {
    const item=items[lightbox];
    if(item) void deleteImages([item.id]);
  });
  $g("gallery-viewer").addEventListener("click",e=>{
    if(e.target===$g("gallery-viewer")||e.target===$g("gallery-viewer-stage"))
      setChrome(!chromeVisible);
  });
  document.addEventListener("keydown",e=>{
    if (lightbox===-1) return;
    if(e.key==="Escape"){e.preventDefault();close();}
    else if(e.key==="ArrowLeft"){e.preventDefault();void shift(-1);}
    else if(e.key==="ArrowRight"){e.preventDefault();void shift(1);}
  });
  const wrap=$g("gallery-viewer-wrap");
  const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
  const middle=(a,b)=>({x:(a.x+b.x)/2,y:(a.y+b.y)/2});
  wrap.addEventListener("pointerdown",e=>{
    // The NSFW cover is a visual shield, not a gesture blocker. Only its
    // explicit Reveal button should consume taps; swiping the covered image
    // must navigate without revealing the current or neighboring artworks.
    if (e.target.closest("button")) return;
    e.preventDefault();
    wrap.setPointerCapture(e.pointerId);
    fingers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if (fingers.size===1) {
      dragStart={x:e.clientX,y:e.clientY,panX,panY,started:Date.now(),moved:false};
      pinch=null;
    } else if(fingers.size===2){
      const [a,b]=[...fingers.values()];
      pinch={initialDistance:Math.max(1,distance(a,b)),initialScale:zoom,lastMid:middle(a,b)};
      dragStart=null;
      if(tapTimer){clearTimeout(tapTimer);tapTimer=null;}
    }
  });
  wrap.addEventListener("pointermove",e=>{
    if(!fingers.has(e.pointerId))return;
    e.preventDefault();
    fingers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(fingers.size>=2 && pinch){
      const [a,b]=[...fingers.values()],mid=middle(a,b);
      setZoom(pinch.initialScale*distance(a,b)/pinch.initialDistance,mid.x,mid.y);
      panX+=mid.x-pinch.lastMid.x;panY+=mid.y-pinch.lastMid.y;
      pinch.lastMid=mid;clampPan();applyZoom();
    } else if(fingers.size===1 && dragStart){
      const dx=e.clientX-dragStart.x,dy=e.clientY-dragStart.y;
      if(Math.abs(dx)>9||Math.abs(dy)>9)dragStart.moved=true;
      if(zoom>1.01){panX=dragStart.panX+dx;panY=dragStart.panY+dy;clampPan();applyZoom();}
    }
  });
  const endPointer=e=>{
    if(!fingers.has(e.pointerId))return;
    const start=dragStart;
    fingers.delete(e.pointerId);
    if(pinch){
      if(fingers.size<2){pinch=null;dragStart=null;}
      return;
    }
    if(start && fingers.size===0){
      const dx=e.clientX-start.x,dy=e.clientY-start.y;
      if(zoom<=1.01 && Math.abs(dx)>65 && Math.abs(dx)>Math.abs(dy)*1.2){
        lastTap=null;
        void shift(dx>0?-1:1);
      }else if(!start.moved && Date.now()-start.started<500){
        const now=Date.now();
        if(lastTap && now-lastTap.time<310 &&
            Math.hypot(e.clientX-lastTap.x,e.clientY-lastTap.y)<36){
          if(tapTimer){clearTimeout(tapTimer);tapTimer=null;}
          setZoom(zoom>1.01?1:2.2,e.clientX,e.clientY);
          lastTap=null;
        }else{
          lastTap={time:now,x:e.clientX,y:e.clientY};
          if(tapTimer)clearTimeout(tapTimer);
          tapTimer=setTimeout(()=>{tapTimer=null;setChrome(!chromeVisible);},320);
        }
      }
    }
    dragStart=null;
  };
  wrap.addEventListener("pointerup",endPointer);
  wrap.addEventListener("pointercancel",endPointer);
  wrap.addEventListener("wheel",e=>{
    if(lightbox===-1)return;
    e.preventDefault();
    setZoom(zoom*(e.deltaY<0?1.2:1/1.2),e.clientX,e.clientY);
  },{passive:false});
  $g("gallery-full").addEventListener("load",finishFullImage);
  $g("gallery-full").addEventListener("error",()=>{
    if (lightbox===-1 || $g("gallery-full").getAttribute("src")!==expectedFullSrc) return;
    $g("gallery-image-loading").textContent="高清图加载失败，显示预览图";
    $g("gallery-image-loading").hidden=false;
  });
  window.addEventListener("resize",()=>{if(lightbox!==-1){clampPan();applyZoom();}});
  setInterval(()=>{if(lightbox!==-1)void checkUpscaleJobs();},2300);
  window.MikuchinGallery={refresh:()=>load(true)};
  if(location.hash==="#gallery")void load(true);
})();
