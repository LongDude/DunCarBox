import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';

const localChrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5174';
export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL,
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: {
      executablePath:
        process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ||
        (existsSync(localChrome) ? localChrome : undefined),
      args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    },
  },
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER ? undefined : {
    command: `npm run dev -- --host 127.0.0.1 --port ${new URL(baseURL).port || '5173'} --force`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
  },
});
