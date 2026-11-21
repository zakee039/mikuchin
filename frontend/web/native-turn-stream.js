/* Incremental, bounded server-sent-event framing for Native Tool Calling. */
"use strict";
(function(root){
  class Decoder {
    constructor(onEvent){this.onEvent=onEvent;this.buffer="";this.completed=false;}
    push(chunk){
      this.buffer+=String(chunk);
      if(this.buffer.length>1048576)throw Error("Native tool stream frame too large");
      let index;
      while((index=this.buffer.indexOf("\n"))>=0){
        const line=this.buffer.slice(0,index).trim();
        this.buffer=this.buffer.slice(index+1);
        if(!line.startsWith("data:"))continue;
        const raw=line.slice(5).trim();
        if(raw==="[DONE]")continue;
        let event;
        try{event=JSON.parse(raw);}catch(_){throw Error("Invalid Native tool stream event");}
        if(!event || typeof event!=="object" || typeof event.type!=="string")
          throw Error("Invalid Native tool event shape");
        if(event.type==="done")this.completed=true;
        this.onEvent(event);
      }
    }
    finish(){
      if(this.buffer.trim())throw Error("Incomplete Native tool stream frame");
      if(!this.completed)throw Error("Native tool stream ended without a confirmed result");
    }
  }
  const api=Object.freeze({Decoder});
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  if(root)root.MikuchinToolStream=api;
})(typeof window!=="undefined"?window:undefined);
