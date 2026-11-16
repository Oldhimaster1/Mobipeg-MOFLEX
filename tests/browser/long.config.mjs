import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'.',testMatch:'long.spec.mjs',workers:1,timeout:240000,use:{baseURL:'http://127.0.0.1:4173',headless:true},reporter:'list'});
