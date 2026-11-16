import{defineConfig,devices}from'@playwright/test';
export default defineConfig({testDir:'tests/browser',use:{baseURL:'http://127.0.0.1:4173'},webServer:{command:'node scripts/dev-server.mjs',port:4173,reuseExistingServer:true},projects:[{name:'chromium',use:{...devices['Desktop Chrome']}},{name:'firefox',use:{...devices['Desktop Firefox']}},{name:'webkit',use:{...devices['iPhone 13']}}]});
