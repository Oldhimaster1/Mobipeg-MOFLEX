const VERSION = '20261118w';
const scope = new URL(self.registration.scope);
const PREFIX = 'mobipeg-offline-'+scope.pathname+'-';
const CACHE = PREFIX+VERSION;
const asset = name => new URL(name,scope).href;
const ready = asset('.mobipeg-offline-ready');
let installation;

async function installOffline() {
  const cache = await caches.open(CACHE);
  if(await cache.match(ready))return;
  try{
    const manifest = await fetch(asset('offline-assets.json'),{cache:'no-store'});
    if(!manifest.ok)throw Error('Could not load the offline file list.');
    const {version,files}=await manifest.json();
    if(version!==VERSION)throw Error('An update is being published. Reload Web Studio and try again.');
    for(const [name,expected] of Object.entries(files)){
      const url=asset(name);
      const response=await fetch(url,{cache:'no-store'});
      if(!response.ok)throw Error('Could not save '+name+' for offline use.');
      const bytes=await response.arrayBuffer();
      const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));
      const actual=Array.from(digest,byte=>byte.toString(16).padStart(2,'0')).join('');
      if(actual!==expected)throw Error('Offline files changed during setup. Reload and try again.');
      const headers=new Headers(response.headers);
      headers.delete('Content-Encoding');
      headers.delete('Content-Length');
      await cache.put(url,new Response(bytes,{headers}));
    }
    await cache.put(ready,new Response('ready'));
  }catch(error){
    await caches.delete(CACHE);
    throw error;
  }
}

function prepareOffline(){
  if(!installation)installation=installOffline().finally(()=>{installation=undefined;});
  return installation;
}

self.addEventListener('install',event=>event.waitUntil((async()=>{
  for(const key of await caches.keys()){
    if(key!==CACHE&&key.startsWith(PREFIX)&&(await (await caches.open(key)).match(ready))){
      await prepareOffline();
      break;
    }
  }
  if(!self.registration.active)await self.skipWaiting();
})()));

self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const key of await caches.keys())if(key!==CACHE&&key.startsWith(PREFIX))await caches.delete(key);
  await self.clients.claim();
})()));

self.addEventListener('message',event=>{
  const port=event.ports[0];
  if(!port)return;
  event.waitUntil((async()=>{
    try{
      if(event.data?.type==='install-offline')await prepareOffline();
      const available=await caches.has(CACHE)&&!!(await (await caches.open(CACHE)).match(ready));
      port.postMessage({available});
    }catch(error){port.postMessage({error:error.message});}
  })());
});

self.addEventListener('fetch',event=>{
  const request=event.request,url=new URL(request.url);
  if(request.method!=='GET'||url.origin!==scope.origin||!url.pathname.startsWith(scope.pathname))return;
  event.respondWith((async()=>{
    let response;
    if(!request.headers.has('Range')&&await caches.has(CACHE)){
      const cache=await caches.open(CACHE);
      if(await cache.match(ready)){
        const urlWithoutQuery=url.pathname===scope.pathname?asset('index.html'):url.origin+url.pathname;
        response=await cache.match(urlWithoutQuery);
      }
    }
    response??=await fetch(request);
    if(response.type==='opaque'||response.status===0)return response;
    const headers=new Headers(response.headers);
    headers.set('Cross-Origin-Opener-Policy','same-origin');
    headers.set('Cross-Origin-Embedder-Policy','require-corp');
    headers.set('Cross-Origin-Resource-Policy','same-origin');
    return new Response(response.body,{status:response.status,statusText:response.statusText,headers});
  })());
});
