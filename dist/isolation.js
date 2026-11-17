// The same worker supplies isolation on static hosting and verified offline assets.
let installPrompt;
window.addEventListener('beforeinstallprompt',event=>{
  event.preventDefault();
  installPrompt=event;
});

function askWorker(worker,type){
  return new Promise((resolve,reject)=>{
    const channel=new MessageChannel();
    channel.port1.onmessage=({data})=>{
      channel.port1.close();
      if(data.error)reject(Error(data.error));
      else resolve(data);
    };
    worker.postMessage({type},[channel.port2]);
  });
}

(async()=>{
  if(!('serviceWorker' in navigator))return;
  try{
    const registration=await navigator.serviceWorker.register('isolation-sw.js');
    const active=await navigator.serviceWorker.ready;
    if(!self.crossOriginIsolated&&!sessionStorage.getItem('mobipeg-isolation-reload')){
      sessionStorage.setItem('mobipeg-isolation-reload','1');
      if(navigator.serviceWorker.controller)location.reload();
      else navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});
      return;
    }
    const footer=document.querySelector('footer');
    if(!footer)return;
    const panel=document.createElement('div');
    const button=document.createElement('button');
    const install=document.createElement('button');
    const status=document.createElement('span');
    button.type=install.type='button';
    button.className=install.className='text-button';
    button.id='offlineSetup';
    button.textContent='Save app for offline use';
    install.textContent='Install app';
    install.hidden=!installPrompt;
    window.addEventListener('beforeinstallprompt',()=>{install.hidden=false;});
    install.onclick=async()=>{
      if(!installPrompt)return;
      await installPrompt.prompt();
      installPrompt=undefined;
      install.hidden=true;
    };
    status.id='offlineStatus';
    status.setAttribute('role','status');
    panel.append(button,' ',install,' ',status);
    footer.append(panel);
    const show=available=>{
      button.disabled=available;
      if(available)status.textContent='Ready offline. On iPhone or iPad, use Share → Add to Home Screen to install.';
    };
    show((await askWorker(active.active,'offline-status')).available);
    button.onclick=async()=>{
      button.disabled=true;
      status.textContent='Saving the app and both encoders (about 40 MB)…';
      try{
        const result=await askWorker(registration.active,'install-offline');
        show(result.available);
      }catch(error){
        button.disabled=false;
        status.textContent=error.message;
      }
    };
  }catch(error){console.warn('Web Studio service worker unavailable:',error.message);}
})();
