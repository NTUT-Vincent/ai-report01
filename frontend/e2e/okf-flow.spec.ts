import { expect, test } from '@playwright/test';

const backend = 'http://localhost:8000';

async function initDb(request: any) {
  const response = await request.post(`${backend}/db/init`);
  expect(response.ok()).toBeTruthy();
}

async function configureAgent(page: any, baseUrl = 'http://localhost:9000/v1') {
  await page.getByTestId('base-url').fill(baseUrl);
  await page.getByTestId('model-name').fill('mock-model');
  await page.getByTestId('api-key').fill('playwright-secret-key');
}

test.beforeEach(async ({ request, page }) => {
  await initDb(request);
  await page.goto('/');
  await configureAgent(page);
});

test('browser completes upload, agent processing, OKF approval, and search', async ({ page }) => {
  const fileName = `playwright-${Date.now()}.txt`;
  await page.locator('input[type="file"]').setInputFiles({
    name: fileName,
    mimeType: 'text/plain',
    buffer: Buffer.from('機台發生 alarm code 時，工程師必須依照 SOP 執行異常處理。'),
  });

  const row = page.locator('tbody tr').filter({ hasText: fileName }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText('RECEIVED');

  await row.getByRole('button', { name: 'Process with Agents' }).click();
  await expect(row).toContainText('ENTITY_REVIEWED');

  await row.getByRole('button', { name: 'Build OKF with Agent' }).click();
  await expect(row).toContainText('OKF_REVIEW_PENDING');

  await row.getByRole('button', { name: 'Approve latest OKF' }).click();
  await expect(row).toContainText(/APPROVED|READY/);

  await page.getByRole('tab', { name: 'Search' }).click();
  await page.getByTestId('search-input').fill('機台');
  await page.getByTestId('search-button').click();
  await expect(page.getByTestId('search-results')).toContainText('機台');
});

test('browser shows a safe error when the model endpoint is unreachable', async ({ page }) => {
  await configureAgent(page, 'http://localhost:65530/v1');
  const fileName = `broken-model-${Date.now()}.txt`;
  await page.locator('input[type="file"]').setInputFiles({
    name: fileName,
    mimeType: 'text/plain',
    buffer: Buffer.from('This document validates model connection error handling.'),
  });

  const row = page.locator('tbody tr').filter({ hasText: fileName }).first();
  await expect(row).toContainText('RECEIVED');
  await row.getByRole('button', { name: 'Process with Agents' }).click();
  await expect(page.getByText(/Process failed:/)).toBeVisible();
  await expect(row).toContainText('AGENT_FAILED');
  await expect(page.getByText('playwright-secret-key')).toHaveCount(0);
});
