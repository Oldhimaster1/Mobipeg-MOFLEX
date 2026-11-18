// WebKit can leave existing pthread instances with stale bounds after shared
// memory grows. Reserve the working heap before creating the pool. Chromium's
// smaller default is retained. This is per command, not a movie-sized buffer.
export function wasmRuntimeOptions(userAgent=globalThis.navigator?.userAgent||'',initialMiB=128){
  const webkit=/AppleWebKit\//.test(userAgent)&&!/Chrom(?:e|ium)\/|Edg\//.test(userAgent);
  return webkit?{wasmMemory:new WebAssembly.Memory({initial:initialMiB*16,maximum:32768,shared:true})}:{};
}
