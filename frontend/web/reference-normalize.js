/* Browser-side repair of reference images before Native draft storage.
 * The canvas decode/encode strips broken metadata / ancillary chunks.
 * Small bounded WebP blobs also keep up to 8 references below the Gateway's
 * 8 MiB JSON request size without disabling server-side validation.
 */
"use strict";
(function (root) {
  const MAX_EDGE=2048, MAX_PIXELS=4_000_000, TARGET_BYTES=640*1024;
  const ACCEPTED=new Set(["image/png","image/jpeg","image/webp"]);
  function toBlob(canvas,type,quality){
    return new Promise((resolve,reject)=>{
      canvas.toBlob(blob=>blob?resolve(blob):reject(Error("参考图编码失败")),type,quality);
    });
  }
  async function decode(file) {
    if(typeof createImageBitmap==="function"){
      try {return await createImageBitmap(file);} catch(_) {
        // Some browser image elements decode files that createImageBitmap
        // refuses because of non-critical container metadata.
      }
    }
    const src=URL.createObjectURL(file);
    try{
      return await new Promise((resolve,reject)=>{
        const img=new Image();
        img.onload=()=>resolve(img);
        img.onerror=()=>reject(Error("浏览器也无法解码这张图片"));
        img.src=src;
      });
    }finally{URL.revokeObjectURL(src);}
  }
  async function normalize(file) {
    if (!file || !ACCEPTED.has(file.type) || file.size<1 || file.size>5*1024*1024)
      throw Error("仅支持小于 5 MB 的 PNG、JPEG、WebP 图片");
    let bitmap;
    try {
      bitmap=await decode(file);
      const sourceWidth=bitmap.naturalWidth||bitmap.width;
      const sourceHeight=bitmap.naturalHeight||bitmap.height;
      if (!sourceWidth || !sourceHeight || sourceWidth*sourceHeight>28_000_000)
        throw Error("参考图尺寸过大");
      const ratio=Math.min(1,MAX_EDGE/sourceWidth,MAX_EDGE/sourceHeight,
                            Math.sqrt(MAX_PIXELS/(sourceWidth*sourceHeight)));
      let width=Math.max(1,Math.round(sourceWidth*ratio));
      let height=Math.max(1,Math.round(sourceHeight*ratio));
      const canvas=document.createElement("canvas");
      const ctx=canvas.getContext("2d",{alpha:true});
      if (!ctx) throw Error("浏览器无法创建图片画布");
      let result=null;
      for (let pass=0; pass<7; pass++) {
        canvas.width=width;canvas.height=height;
        ctx.drawImage(bitmap,0,0,width,height);
        // Prefer WebP: preserves alpha, usually smaller than PNG/JPEG, and
        // is accepted by the already existing Native reference pipeline.
        result=await toBlob(canvas,"image/webp",pass<3?.88-pass*.08:.70);
        if (result.type==="image/webp" && result.size<=TARGET_BYTES) break;
        // Older Safari/embedded WebViews may not support WebP encoding.
        // Keep a small PNG with transparency, or fall back to JPEG if
        // this image is too large for the Gateway's multi-image request.
        if (result.type!=="image/webp") {
          if(result.type==="image/png" && result.size<=TARGET_BYTES) break;
          ctx.globalCompositeOperation="destination-over";
          ctx.fillStyle="#ffffff";
          ctx.fillRect(0,0,width,height);
          ctx.globalCompositeOperation="source-over";
          result=await toBlob(canvas,"image/jpeg",pass<3?.86:.70);
          if (result.type==="image/jpeg" && result.size<=TARGET_BYTES) break;
        }
        if (pass===6) throw Error("图片重新编码后仍过大，请裁剪或缩小图片");
        width=Math.max(1,Math.round(width*.82));
        height=Math.max(1,Math.round(height*.82));
      }
      return result;
    } catch(error) {
      throw Error("无法自动修复参考图：" + String(error?.message||error));
    } finally {
      bitmap?.close?.();
    }
  }
  const api=Object.freeze({normalize,MAX_EDGE,MAX_PIXELS,TARGET_BYTES});
  if(typeof module!=="undefined" && module.exports)module.exports=api;
  if(root) root.MikuchinReferenceNormalizer=api;
})(typeof window!=="undefined"?window:undefined);
