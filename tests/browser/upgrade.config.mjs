import {defineConfig} from '@playwright/test';
const browserName=process.env.MOBIPEG_TEST_BROWSER||'chromium';
const browserPath=browserName==='chromium'?process.env.MOBIPEG_TEST_CHROMIUM_PATH:null;
export default defineConfig({
  testDir:'.',testMatch:['upgrade.spec.mjs','cia-packaging.spec.mjs','cia-design.spec.mjs'],workers:1,timeout:180000,
  webServer:{command:'node scripts/dev-server.mjs',cwd:new URL('../..',import.meta.url).pathname,
    url:'http://127.0.0.1:4173',reuseExistingServer:true},
  use:{browserName,baseURL:'http://127.0.0.1:4173',headless:true,
    ...(browserPath?{launchOptions:{executablePath:browserPath}}:{})},
});
