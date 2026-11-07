import { test, expect } from '@playwright/test';
const config = { region: 'us-east-1', issuer: 'https://cognito-idp.us-east-1.amazonaws.com/test', clientId: 'test-client',
  apiUrl: 'https://test.execute-api.us-east-1.amazonaws.com', cognitoDomain: 'https://test.auth.us-east-1.amazoncognito.com', appUrl: 'http://127.0.0.1:8088/' };
const sample = {
  '/items': { items: [{ id: '1', name: 'Eggs', location: 'Fridge', zone: 3, version: 1 }, { id: '2', name: '<img src=x onerror=alert(1)>', location: 'Pantry', zone: null, version: 1 }] },
  '/locations': { items: [{ id: 'loc1', location: 'Fridge' }, { id: 'loc2', location: 'Pantry' }] },
  '/impromptu': { items: [{ id: 'i1', name: 'Bread', version: 1 }] },
  '/shopping': { costco: [{ id: 'c1', items: 'Eggs' }], harris_teeter: [{ id: 'h1', items: 'Tea' }], impromptu: [{ id: 'i1', name: 'Bread' }] },
  '/meals': { items: [{ id: 'm1', meal: 'Soup', last_eaten: '2026-01-01', tags: ['chicken', 'summer dish'], version: 1 }] },
};
async function setup(page, loggedIn = true, expiresIn = 3600) {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/config.js', route => route.fulfill({ contentType: 'application/javascript', body: `window.APP_CONFIG=${JSON.stringify(config)}` }));
  if (loggedIn) await page.addInitScript(({ config, expiresIn }) => {
    localStorage.setItem(`oidc.user:${config.issuer}:${config.clientId}`, JSON.stringify({
      access_token: 'mock-access-token', refresh_token: 'mock-refresh-token', token_type: 'Bearer',
      scope: 'openid email aws.cognito.signin.user.admin grocery/read grocery/write', expires_at: Math.floor(Date.now()/1000) + expiresIn,
      profile: { sub: 'test-user', email: 'test@example.test', iss: config.issuer, aud: config.clientId },
    }));
  }, { config, expiresIn });
  await page.route(`${config.apiUrl}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === 'GET') await route.fulfill({ json: sample[path] || {} });
    else await route.fulfill({ json: { ok: true } });
  });
  return errors;
}

test('login redirect uses code and PKCE, no secret', async ({ page }) => {
  await setup(page, false);
  await page.goto('/');
  let auth;
  await page.route(`${config.cognitoDomain}/**`, route => { auth = new URL(route.request().url()); return route.fulfill({ body: 'Mock Cognito' }); });
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect.poll(() => auth?.searchParams.get('code_challenge_method')).toBe('S256');
  expect(auth.searchParams.get('response_type')).toBe('code');
  expect(auth.searchParams.has('state')).toBe(true);
  expect(auth.searchParams.has('client_secret')).toBe(false);
});

test('all screens render and hostile item names are plain text', async ({ page }) => {
  const errors = await setup(page);
  for (const [route, heading] of [['home', 'Welcome to Household Groceries'], ['inventory', 'Shopping List'], ['costco', 'Costco List'], ['after-costco', 'After Costco'], ['harris-teeter', 'Harris Teeter List'], ['impromptu', 'Impromptu List'], ['manage', 'Manage Inventory'], ['meals', 'Meals'], ['password', 'Change password']]) {
    await page.goto(`/#${route}`);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  await page.goto('/#inventory');
  await expect(page.getByText('<img src=x onerror=alert(1)>', { exact: true })).toBeVisible();
  await expect(page.locator('main img')).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('shopping save sends source IDs with idempotency key', async ({ page }) => {
  await setup(page);
  await page.goto('/#inventory');
  await page.getByRole('group', { name: 'Eggs', exact: true }).getByLabel('Costco', { exact: true }).check();
  const requestPromise = page.waitForRequest(request => request.url().endsWith('/shopping/selections'));
  await page.getByRole('button', { name: 'Save Changes' }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({ entries: [{ id: '1', kind: 'items', store: 'costco' }] });
  expect(request.headers()['idempotency-key']).toBeTruthy();
  await expect(page.getByRole('status')).toContainText('Changes saved.');
});

test('network retry reuses key and does not lose submitted body', async ({ page }) => {
  await setup(page);
  let attempts = [];
  await page.route(`${config.apiUrl}/impromptu`, async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: sample['/impromptu'] });
    attempts.push({ key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON() });
    if (attempts.length === 1) return route.abort('failed');
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto('/#impromptu');
  await page.getByLabel('New impromptu item').fill('Oranges');
  await page.getByRole('button', { name: 'Submit', exact: true }).click();
  await page.getByRole('button', { name: 'Retry pending save', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Changes saved.');
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);
});

test('clear requires confirmation and resets all lists in one API call', async ({ page }) => {
  await setup(page);
  await page.goto('/#impromptu');
  page.once('dialog', dialog => { expect(dialog.message()).toContain('Costco'); dialog.accept(); });
  const requestPromise = page.waitForRequest(request => request.url().endsWith('/shopping/reset'));
  await page.getByRole('button', { name: 'Clear List', exact: true }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({});
});

test('login persists on reload without a new authorization request', async ({ page }) => {
  await setup(page);
  await page.goto('/#meals');
  await expect(page.getByRole('heading', { name: 'Meals', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Meals', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
});

test('expired access token renews through persisted refresh token', async ({ page }) => {
  await setup(page, true, -60);
  let refreshBody;
  await page.route(`${config.cognitoDomain}/oauth2/token`, route => {
    refreshBody = new URLSearchParams(route.request().postData());
    return route.fulfill({ json: { access_token: 'renewed-access-token', refresh_token: 'mock-refresh-token', expires_in: 3600, token_type: 'Bearer', scope: 'openid email aws.cognito.signin.user.admin grocery/read grocery/write' } });
  });
  await page.goto('/#meals');
  await expect(page.getByRole('heading', { name: 'Meals', exact: true })).toBeVisible();
  expect(refreshBody.get('grant_type')).toBe('refresh_token');
  expect(refreshBody.get('refresh_token')).toBe('mock-refresh-token');
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)).access_token, `oidc.user:${config.issuer}:${config.clientId}`)).toBe('renewed-access-token');
});

test('login callback errors do not leave a banner on every page', async ({ page }) => {
  await setup(page);
  await page.goto('/?error=access_denied&error_description=Sign-in+cancelled');
  await expect(page.locator('#status')).toHaveText('');
  await page.goto('/#meals');
  await expect(page.getByRole('heading', { name: 'Meals', exact: true })).toBeVisible();
  await expect(page.locator('#status')).toHaveText('');
});

test('meal tags display and save on existing and new meals', async ({ page }) => {
  const viewport = page.viewportSize();
  test.skip(!viewport || viewport.width <= 500, 'Tag editing is hidden on mobile');
  await setup(page);
  await page.goto('/#meals');
  await expect(page.getByText('chicken', { exact: true })).toBeVisible();
  await expect(page.getByText('summer dish', { exact: true })).toBeVisible();
  await page.getByLabel('Tags for Soup').fill('Chicken, summer dish');
  const editRequest = page.waitForRequest(request => request.url().endsWith('/meals/m1') && request.method() === 'PATCH');
  await page.getByRole('button', { name: 'Save Tags' }).click();
  const edit = await editRequest;
  expect(edit.postDataJSON()).toEqual({ tags: ['Chicken', 'summer dish'], version: 1 });
  expect(edit.headers()['idempotency-key']).toBeTruthy();

  await page.getByLabel('Meal name').fill('Veggie tacos');
  await page.getByLabel('Tags (comma-separated; up to 5)').fill('summer dish, vegetarian');
  const addRequest = page.waitForRequest(request => request.url().endsWith('/meals') && request.method() === 'POST');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  const add = await addRequest;
  expect(add.postDataJSON()).toEqual({ meal: 'Veggie tacos', tags: ['summer dish', 'vegetarian'] });
});

test('mobile meal rows show only name, last-eaten date, and delete', async ({ page }) => {
  const viewport = page.viewportSize();
  test.skip(!viewport || viewport.width > 500, 'Mobile-only layout check');
  await setup(page);
  await page.goto('/#meals');
  const row = page.locator('.entries.meals li');
  await expect(row.getByText('Soup', { exact: true })).toBeVisible();
  await expect(row.getByText('Last Eaten: 2026-01-01')).toBeVisible();
  await expect(row.getByRole('button', { name: 'Delete', exact: true })).toBeVisible();
  await expect(row.locator('.meal-tag-list')).toBeHidden();
  await expect(row.locator('.meal-tags-form')).toBeHidden();
  await expect(page.locator('.meal-add-tags')).toBeVisible();
  await expect(page.getByLabel('Tags (comma-separated; up to 5)')).toBeVisible();
});

test('meal tag count is limited to five in the UI', async ({ page }) => {
  const viewport = page.viewportSize();
  test.skip(!viewport || viewport.width <= 500, 'Tag editing is hidden on mobile');
  await setup(page);
  await page.goto('/#meals');
  const writes = [];
  page.on('request', request => { if (request.url().endsWith('/meals') && request.method() === 'POST') writes.push(request); });
  await page.getByLabel('Meal name').fill('Soup');
  await page.getByLabel('Tags (comma-separated; up to 5)').fill('a, b, c, d, e, f');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('at most 5 tags');
  expect(writes).toHaveLength(0);
});

test('meals delete buttons are concise and Add New Meal card is last', async ({ page }) => {
  await setup(page);
  await page.goto('/#meals');
  await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Delete Soup', exact: true })).toHaveCount(0);
  const headings = await page.locator('main > div > section > h2').allTextContents();
  expect(headings.at(-1)).toBe('Add new meal');
});

test('Costco groups catalog zones and automatically includes impromptu', async ({ page }) => {
  await setup(page);
  await page.goto('/#costco');
  await expect(page.locator('section').filter({ has: page.getByRole('heading', { name: 'Zone 3', exact: true }) })).toContainText('Eggs');
  await expect(page.locator('section').filter({ has: page.getByRole('heading', { name: 'Impromptu', exact: true }) })).toContainText('Bread');
});
