import { defineConfig, devices } from '@playwright/test';

/**
 * 세무 AI 에이전트 (Streamlit) 맞춤형 Playwright E2E 전수 실증 설정
 * 참고 공식 문서: https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './tests',
  timeout: 60 * 1000,
  expect: {
    timeout: 15 * 1000,
  },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8501',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    viewport: { width: 1920, height: 1080 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'streamlit run app.py --server.port 8501 --server.headless true',
    url: 'http://localhost:8501',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
});
