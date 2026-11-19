// Private image fetcher for the native Gateway. Never put Bearer keys in URLs,
// query strings, <img src>, redirects or persistent browser caches.
"use strict";
(() => {
  const allowed = /^(?:v1\/images\/files\/[a-f0-9]{32}\.png|v1\/mikuchin\/gallery\/thumb\/[a-f0-9]{32}|v1\/mikuchin\/image-job-reference\/[a-f0-9]{64})$/;
  const active = new WeakMap();
  const attached = new Set();
  const cache = new Map();
  const pending = new Map();
  let bytes = 0;
  let authorization = null, epoch = 0;
  const cap = 64 * 1024 * 1024;

  function requirePath(path) {
    if (typeof path !== "string" || !allowed.test(path))
      throw Error("Private image path is invalid");
    return path;
  }
  function clearCache(releaseVisible = false) {
    epoch++;
    cache.clear();pending.clear();bytes=0;
    if (releaseVisible) for (const img of [...attached]) release(img);
  }
  function authorizedHeaders() {
    const result = headers();
    const next = result.Authorization || result.authorization || "";
    if (authorization !== null && next !== authorization) clearCache(true);
    authorization = next;
    return result;
  }
  async function getBlob(path) {
    requirePath(path);
    const auth = authorizedHeaders();
    const requestEpoch=epoch;
    if (cache.has(path)) {
      const entry = cache.get(path);
      cache.delete(path);cache.set(path,entry);
      return entry.blob;
    }
    if (pending.has(path)) return pending.get(path);
    const work = (async () => {
      const response = await fetch(path,{headers:auth,cache:"no-store",credentials:"same-origin"});
      if (!response.ok) throw Error("Private image HTTP " + response.status);
      const length = Number(response.headers.get("Content-Length"));
      if (length > 40 * 1024 * 1024) throw Error("Image exceeds memory limit");
      const blob = await response.blob();
      if (requestEpoch !== epoch) throw Error("Image authorization changed");
      if (!/^image\/(?:png|jpeg|webp)$/.test(blob.type) || blob.size > 40*1024*1024)
        throw Error("Unexpected private image response");
      if (blob.size <= cap) {
        cache.set(path,{blob,size:blob.size});bytes+=blob.size;
        while ((bytes > cap || cache.size > 100) && cache.size) {
          const [first,entry] = cache.entries().next().value;
          cache.delete(first);bytes-=entry.size;
        }
      }
      return blob;
    })().finally(() => {if (pending.get(path)===work) pending.delete(path);});
    pending.set(path,work);
    return work;
  }
  function release(img) {
    const previous = active.get(img);
    if (previous?.blobUrl) URL.revokeObjectURL(previous.blobUrl);
    if (previous) {
      active.delete(img);
      attached.delete(img);
      img.removeAttribute("src");
    }
  }
  function path(img) {return active.get(img)?.path || "";}
  async function load(img,resource) {
    requirePath(resource);
    const previous = active.get(img);
    if (previous?.path === resource) return previous.promise;
    release(img);
    const state = {path:resource,blobUrl:"",promise:null};
    active.set(img,state);
    attached.add(img);
    state.promise = getBlob(resource).then(blob => {
      if (active.get(img) !== state) return false;
      state.blobUrl=URL.createObjectURL(blob);
      img.src=state.blobUrl;
      return true;
    }).catch(error => {
      if (active.get(img) === state) release(img);
      throw error;
    });
    return state.promise;
  }
  function clearWithin(root) {
    if (!root) return;
    for (const img of root.querySelectorAll("img")) release(img);
  }
  function forget(path) {
    const entry=cache.get(path);
    if (entry) {cache.delete(path);bytes-=entry.size;}
  }
  const api=Object.freeze({load,release,clearWithin,clearCache,forget,prefetch:getBlob,path});
  if (typeof window !== "undefined") window.MikuchinSecureImages=api;
  if (typeof module !== "undefined" && module.exports) module.exports=api;
})();
