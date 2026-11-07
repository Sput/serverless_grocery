import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:8088' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: {
    command: `${process.env.GROCERY_PYTHON || '.tools/lambda-venv/bin/python'} -m http.server 8088 --bind 127.0.0.1 --directory dist`,
    url: 'http://127.0.0.1:8088', reuseExistingServer: false,
  },
});
