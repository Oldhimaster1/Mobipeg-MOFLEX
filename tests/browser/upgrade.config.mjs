import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir:'.',testMatch:'upgrade.spec.mjs',workers:1,timeout:180000,
  webServer:{command:'node scripts/dev-server.mjs',cwd:new URL('../..',import.meta.url).pathname,
    url:'http://127.0.0.1:4173',reuseExistingServer:true},
  use:{baseURL:'http://127.0.0.1:4173',headless:true},
});
