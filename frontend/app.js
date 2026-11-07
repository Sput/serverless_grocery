import { UserManager, WebStorageStateStore } from 'oidc-client-ts';
import { costcoGroups, batches, utcToday } from './logic.js';

const config = window.APP_CONFIG;
const main = document.querySelector('#content');
const status = document.querySelector('#status');
const account = document.querySelector('#account');
const navigation = document.querySelector('#navigation');
let manager;
let currentUser;
let renderVersion = 0;
let busy = false;
let pending = null;
const pendingKey = 'grocery.pendingSubmission.v1';

// User content always becomes text nodes, never HTML.
function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}
function message(text, error = false) {
  status.textContent = text;
  status.className = error ? 'error' : '';
}
function button(text, handler, cls = '') {
  const node = el('button', text, { type: 'button', class: cls });
  node.addEventListener('click', handler);
  return node;
}
function section(parent, title) {
  const result = el('section');
  result.append(el('h2', title)); parent.append(result); return result;
}
function field(form, labelText, input) {
  const id = crypto.randomUUID(); input.id = id;
  form.append(el('label', labelText, { for: id }), input); return input;
}
function input(placeholder = '') {
  const result = el('input', null, { type: 'text', maxlength: '200', placeholder, required: '' });
  return result;
}
function select(options) {
  const result = el('select');
  for (const [value, label] of options) result.append(el('option', label, { value }));
  return result;
}
function list(parent, values, empty = 'No items found.') {
  if (!values.length) { parent.append(el('p', empty)); return; }
  const ul = el('ul');
  for (const value of values) ul.append(el('li', value));
  parent.append(ul);
}
function signIn() {
  return manager.signinRedirect({ state: { route: location.hash || '#home' } });
}
async function signOut() {
  try { await manager.revokeTokens(['refresh_token']); } catch { /* Still clear local state. */ }
  await manager.removeUser();
  sessionStorage.removeItem(pendingKey);
  pending = null;
  const url = new URL(`${config.cognitoDomain}/logout`);
  url.search = new URLSearchParams({ client_id: config.clientId, logout_uri: config.appUrl });
  location.assign(url);
}
async function api(path, method = 'GET', body, key) {
  let user = await manager.getUser();
  if (!user || user.expired) {
    try { user = await manager.signinSilent(); }
    catch { throw new Error('Your session expired. Sign in again.'); }
  }
  if (!user) throw new Error('Sign in required.');
  const headers = { Authorization: `Bearer ${user.access_token}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  let response;
  try {
    response = await fetch(`${config.apiUrl}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch { throw new Error('Connection failed. Your submission can be retried safely.'); }
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return payload;
}
function controlsDisabled(value) {
  busy = value;
  for (const node of main.querySelectorAll('button,input,select')) node.disabled = value;
}
function persistPending() {
  if (pending) sessionStorage.setItem(pendingKey, JSON.stringify(pending));
  else sessionStorage.removeItem(pendingKey);
}
async function runPending() {
  if (busy || !pending) return;
  controlsDisabled(true);
  message('Saving…');
  try {
    while (pending.index < pending.jobs.length) {
      const job = pending.jobs[pending.index];
      await api(job.path, job.method, job.body, job.key);
      pending.index += 1; persistPending();
    }
    pending = null; persistPending();
    message('Changes saved.');
    await render();
  } catch (error) {
    // 4xx validation/conflict means this operation did not commit. Discard the
    // pending operation so a reload can rebuild it using fresh versions/data.
    if ([400, 403, 404, 409, 413].includes(error.status)) {
      pending = null; persistPending();
      message(`${error.message} Earlier batches, if any, remain saved. Reload before retrying.`, true);
      main.append(button('Reload current screen', () => render()));
    } else {
      message(`${error.message} Use “Retry pending save” rather than submitting again.`, true);
      main.append(button('Retry pending save', runPending));
    }
  } finally { controlsDisabled(false); }
}
async function save(jobs) {
  if (busy) return;
  if (pending) { message('Retry the pending save before making another change.', true); return; }
  if (!jobs.length) { message('Nothing selected.'); return; }
  pending = { owner: currentUser.profile.sub, jobs: jobs.map(job => ({ ...job, key: crypto.randomUUID() })), index: 0 };
  persistPending();
  await runPending();
}
function form(parent, onSubmit) {
  const node = el('form', null, { class: 'stack' });
  node.addEventListener('submit', event => { event.preventDefault(); if (!busy) onSubmit(); });
  parent.append(node); return node;
}
function submit(form, label) { form.append(el('button', label, { type: 'submit' })); }
function job(path, body, method = 'POST') { return { path, method, body }; }
function parseMealTags(value) {
  const tags = value.split(',').map(tag => tag.trim()).filter(Boolean);
  if (tags.length > 5) { message('A meal may have at most 5 tags.', true); return null; }
  if (tags.some(tag => tag.length > 50)) { message('Each tag must be 50 characters or fewer.', true); return null; }
  if (new Set(tags.map(tag => tag.toLowerCase())).size !== tags.length) { message('Meal tags must be unique.', true); return null; }
  return tags;
}
function choices(parent, rows, afterCostco = false) {
  const selected = new Map();
  rows.forEach(row => {
    const fs = el('fieldset');
    fs.append(el('legend', row.name ?? row.items));
    const group = crypto.randomUUID();
    const options = afterCostco ? [['Have', 'Have'], ['harris_teeter', 'Harris Teeter']] : [['Have', 'Have'], ['costco', 'Costco'], ['harris_teeter', 'Harris Teeter']];
    for (const [value, label] of options) {
      const node = el('input', null, { type: 'radio', name: group, value });
      // Original after-Costco screen has no default checked; regular screen defaults Have.
      node.checked = !afterCostco && value === 'Have';
      node.addEventListener('change', () => selected.set(row.id, value));
      const wrapper = el('label'); wrapper.append(node, document.createTextNode(label)); fs.append(wrapper);
    }
    parent.append(fs);
  });
  return selected;
}
async function render() {
  const version = ++renderVersion;
  const route = location.hash.slice(1) || 'home';
  const root = el('div');
  main.replaceChildren(el('p', 'Loading…'));
  for (const link of navigation.querySelectorAll('a')) {
    if (link.hash === `#${route}`) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  }
  try {
    if (route === 'home') {
      root.append(el('h1', 'Welcome to Household Groceries'), el('p', 'Manage your shared inventory, prepare shopping lists, and track meals.'));
      root.append(el('p', 'Start with Shopping selections, then view Costco or Harris Teeter.'));
    } else if (route === 'inventory') {
      root.append(el('h1', 'Shopping List'));
      const [catalog, impromptu] = await Promise.all([api('/items'), api('/impromptu')]);
      const groups = new Map();
      for (const row of catalog.items) {
        const location = row.location?.trim() || 'Unassigned';
        if (!groups.has(location)) groups.set(location, []);
        groups.get(location).push(row);
      }
      const selections = [];
      for (const [location, rows] of groups) selections.push({ rows, selected: choices(section(root, location), rows), kind: 'items' });
      const impSection = section(root, 'Impromptu List');
      if (!impromptu.items.length) impSection.append(el('p', 'The impromptu list is empty.'));
      selections.push({ rows: impromptu.items, selected: choices(impSection, impromptu.items), kind: 'impromptu' });
      root.append(button('Save Changes', () => {
        const entries = selections.flatMap(({ rows, selected, kind }) => rows.filter(row => ['costco', 'harris_teeter'].includes(selected.get(row.id))).map(row => ({ id: row.id, kind, store: selected.get(row.id) })));
        return save(batches(entries).map(entries => job('/shopping/selections', { entries })));
      }));
      root.append(el('small', 'Saving appends selected items. Separate saves may add the same item again, as in the original application.'));
    } else if (route === 'costco') {
      root.append(el('h1', 'Costco List'));
      const [catalog, shopping] = await Promise.all([api('/items'), api('/shopping')]);
      for (const [zone, names] of costcoGroups(catalog.items, shopping.costco, shopping.impromptu)) {
        list(section(root, typeof zone === 'number' ? `Zone ${zone}` : zone), names, 'No items in this section.');
      }
    } else if (route === 'harris-teeter') {
      root.append(el('h1', 'Harris Teeter List'));
      const shopping = await api('/shopping');
      list(root, shopping.harris_teeter.map(row => row.items));
    } else if (route === 'after-costco') {
      root.append(el('h1', 'After Costco'));
      const shopping = await api('/shopping');
      if (!shopping.costco.length) root.append(el('p', 'No Costco items found.'));
      const selected = choices(root, shopping.costco, true);
      root.append(button('Save Changes', () => save(batches(shopping.costco.filter(row => selected.get(row.id) === 'harris_teeter').map(row => row.id)).map(ids => job('/shopping/after-costco', { ids })))));
      root.append(el('small', 'Copies selected items to Harris Teeter; Costco entries remain unchanged.'));
    } else if (route === 'impromptu') {
      root.append(el('h1', 'Impromptu List'));
      const response = await api('/impromptu');
      const ul = el('ul', null, { class: 'entries' });
      for (const row of response.items) {
        const li = el('li'); li.append(el('span', row.name), button(`Delete ${row.name}`, () => save([job(`/impromptu/${row.id}`, { version: row.version }, 'DELETE')]), 'danger')); ul.append(li);
      }
      root.append(ul);
      if (!response.items.length) root.append(el('p', 'The list is empty.'));
      let name;
      const add = form(root, () => save([job('/impromptu', { name: name.value })]));
      name = field(add, 'New impromptu item', input()); submit(add, 'Submit');
      root.append(button('Clear List', () => {
        if (confirm('Clear ALL impromptu, Costco, and Harris Teeter entries? Records will be retained as deleted.')) save([job('/shopping/reset', {})]);
      }, 'danger'));
    } else if (route === 'manage') {
      root.append(el('h1', 'Manage Inventory'));
      const [catalog, places] = await Promise.all([api('/items'), api('/locations')]);
      const locations = places.items.map(row => [row.location, row.location]);
      let itemName, itemLocation;
      const add = form(section(root, 'Add item'), () => save([job('/items', { name: itemName.value, location: itemLocation.value })]));
      itemName = field(add, 'Item name', input());
      itemLocation = field(add, 'Item location', select([['', 'Choose a location'], ...locations])); itemLocation.required = true; submit(add, 'Add Item');
      let locationName;
      const loc = form(section(root, 'Add location'), () => save([job('/locations', { location: locationName.value })]));
      locationName = field(loc, 'Location name', input()); submit(loc, 'Add Location');
      let chosenItem, updatedLocation;
      const update = form(section(root, 'Update item location'), () => {
        const row = catalog.items.find(row => row.id === chosenItem.value);
        if (row) save([job(`/items/${row.id}`, { location: updatedLocation.value, version: row.version }, 'PATCH')]);
      });
      chosenItem = field(update, 'Existing item', select([['', 'Choose an item'], ...catalog.items.map(row => [row.id, row.name])])); chosenItem.required = true;
      updatedLocation = field(update, 'New location', select([['', 'Choose a location'], ...locations])); updatedLocation.required = true; submit(update, 'Update Location');
    } else if (route === 'meals') {
      root.append(el('h1', 'Meals'));
      const response = await api('/meals');
      let chosenMeal;
      const dinner = form(section(root, 'Dinner tonight'), () => {
        const row = response.items.find(row => row.id === chosenMeal.value);
        if (row) save([job(`/meals/${row.id}`, { last_eaten: utcToday(), version: row.version }, 'PATCH')]);
      });
      chosenMeal = field(dinner, 'Meal', select(response.items.map(row => [row.id, row.meal ?? '(unnamed)']))); submit(dinner, 'Dinner');
      const sorted = section(root, 'Meals sorted by last eaten');
      const ul = el('ul', null, { class: 'entries meals' });
      for (const row of response.items) {
        const li = el('li');
        const info = el('div', null, { class: 'meal-info' });
        info.append(el('strong', row.meal ?? '(unnamed)'), el('div', `Last Eaten: ${row.last_eaten ?? 'Never'}`));
        const tags = el('div', null, { class: 'meal-tag-list' });
        for (const tag of row.tags ?? []) tags.append(el('span', tag, { class: 'meal-tag' }));
        if (!(row.tags ?? []).length) tags.append(el('small', 'No tags'));
        info.append(tags); li.append(info);
        let tagsInput;
        const tagsForm = form(li, () => {
          const parsed = parseMealTags(tagsInput.value);
          if (parsed !== null) save([job(`/meals/${row.id}`, { tags: parsed, version: row.version }, 'PATCH')]);
        });
        tagsForm.classList.add('meal-tags-form');
        tagsInput = field(tagsForm, `Tags for ${row.meal ?? 'meal'}`, el('input', null, { type: 'text', maxlength: '254', placeholder: 'chicken, summer dish' }));
        tagsInput.value = (row.tags ?? []).join(', ');
        submit(tagsForm, 'Save Tags');
        li.append(button('Delete', () => {
          if (confirm(`Delete meal “${row.meal}”?`)) save([job(`/meals/${row.id}`, { version: row.version }, 'DELETE')]);
        }, 'danger'));
        ul.append(li);
      }
      sorted.append(ul); if (!response.items.length) sorted.append(el('p', 'No meals found.'));
      let mealName, tagsInput;
      const add = form(section(root, 'Add new meal'), () => {
        const tags = parseMealTags(tagsInput.value);
        if (tags !== null) save([job('/meals', { meal: mealName.value, tags })]);
      });
      mealName = field(add, 'Meal name', input());
      const addTags = el('div', null, { class: 'meal-add-tags' });
      tagsInput = field(addTags, 'Tags (comma-separated; up to 5)', el('input', null, { type: 'text', maxlength: '254', placeholder: 'chicken, summer dish' }));
      add.append(addTags);
      submit(add, 'Add');
    } else if (route === 'password') {
      root.append(el('h1', 'Change password'));
      let oldPassword, newPassword;
      const passwordForm = form(root, async () => {
        controlsDisabled(true);
        try {
          let user = await manager.getUser();
          if (user?.expired) user = await manager.signinSilent();
          if (!user) throw new Error('Sign in again before changing your password.');
          const response = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
            method: 'POST', headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': 'AWSCognitoIdentityProviderService.ChangePassword' },
            body: JSON.stringify({ AccessToken: user.access_token, PreviousPassword: oldPassword.value, ProposedPassword: newPassword.value }),
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.message || 'Password change failed.');
          oldPassword.value = ''; newPassword.value = '';
          message('Password changed.');
        } catch (error) { message(error.message, true); }
        finally { controlsDisabled(false); }
      });
      oldPassword = field(passwordForm, 'Current password', el('input', null, { type: 'password', autocomplete: 'current-password', required: '' }));
      newPassword = field(passwordForm, 'New password', el('input', null, { type: 'password', autocomplete: 'new-password', minlength: '12', required: '' }));
      submit(passwordForm, 'Change Password');
    } else { root.append(el('h1', 'Page not found')); }
    if (version !== renderVersion) return;
    main.replaceChildren(root);
    if (pending) main.prepend(button('Retry pending save', runPending));
  } catch (error) {
    if (version !== renderVersion) return;
    main.replaceChildren(el('h1', 'Unable to load this screen'), el('p', error.message), button('Retry loading', render));
  }
}
async function start() {
  if (!config?.apiUrl || !config?.issuer || !config?.clientId || !config?.cognitoDomain || !config?.appUrl) {
    main.replaceChildren(el('h1', 'Deployment configuration required'), el('p', 'Build config.js from the SAM stack outputs before publishing.')); return;
  }
  manager = new UserManager({
    authority: config.issuer, client_id: config.clientId, redirect_uri: config.appUrl,
    response_type: 'code', scope: 'openid email aws.cognito.signin.user.admin grocery/read grocery/write',
    userStore: new WebStorageStateStore({ store: localStorage }),
    stateStore: new WebStorageStateStore({ store: sessionStorage }),
    automaticSilentRenew: true, loadUserInfo: false,
    metadata: { issuer: config.issuer, authorization_endpoint: `${config.cognitoDomain}/oauth2/authorize`,
      token_endpoint: `${config.cognitoDomain}/oauth2/token`, userinfo_endpoint: `${config.cognitoDomain}/oauth2/userInfo`,
      revocation_endpoint: `${config.cognitoDomain}/oauth2/revoke`, jwks_uri: `${config.issuer}/.well-known/jwks.json` },
  });
  manager.events.addSilentRenewError(() => message('Session renewal failed. Sign in again if requests fail.', true));
  const params = new URLSearchParams(location.search);
  if (params.has('code') || params.has('error')) {
    try {
      const user = await manager.signinRedirectCallback();
      const route = user.state?.route || '#home';
      history.replaceState(null, '', route.startsWith('#') ? route : '#home');
    } catch {
      history.replaceState(null, '', '#home');
      status.textContent = '';
      status.className = '';
    }
  }
  currentUser = await manager.getUser();
  if (currentUser?.expired) {
    try { currentUser = await manager.signinSilent(); } catch { currentUser = null; }
  }
  if (!currentUser) {
    main.replaceChildren(el('h1', 'Welcome to Household Groceries'), el('p', 'Sign in to access your shared household.'), button('Sign in', () => signIn().catch(error => message(error.message, true))));
    return;
  }
  account.append(el('span', currentUser.profile.email || 'Household member'), button('Sign out', signOut, 'secondary'));
  navigation.hidden = false;
  try {
    pending = JSON.parse(sessionStorage.getItem(pendingKey) || 'null');
    if (pending?.owner !== currentUser.profile.sub) { pending = null; persistPending(); }
  } catch { pending = null; persistPending(); }
  window.addEventListener('hashchange', () => { if (!busy) render(); });
  await render();
}
start().catch(error => { message(error.message, true); main.replaceChildren(el('p', 'Application startup failed. Reload to retry.')); });
