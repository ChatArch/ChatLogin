// The default Python page uses the same generated HTTP client as npm/React.
import { createChatLoginClient } from './client.js';
import { labels, loginMessage } from './ui.js';

const root = document.querySelector('.chatlogin');
const form = root?.querySelector('form');
const status = root?.querySelector('.chatlogin__status');
const text = labels['zh-CN'];
let submitting = false;

form?.addEventListener('submit', async event => {
  event.preventDefault();
  if (submitting) return;
  submitting = true;
  const buttons = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
  const disabled = buttons.map(button => button.disabled);
  buttons.forEach(button => { button.disabled = true; });
  form.setAttribute('aria-busy', 'true');
  if (status) status.textContent = text.loggingIn;
  try {
    const sessionURL = root.dataset.sessionUrl;
    if (!sessionURL?.endsWith('/session')) throw new TypeError('Invalid endpoint configuration');
    const client = createChatLoginClient({ basePath: sessionURL.slice(0, -'/session'.length) });
    if (root.dataset.loginUrl !== client.basePath + '/login') throw new TypeError('Invalid endpoint configuration');
    const result = await client.login({ username: form.elements.username.value,
      password: form.elements.password.value, next: root.dataset.next || '/' });
    window.location.assign(result.next);
  } catch (error) {
    if (status) status.textContent = loginMessage(error);
  } finally {
    form.elements.password.value = '';
    submitting = false;
    buttons.forEach((button, index) => { button.disabled = disabled[index]; });
    form.removeAttribute('aria-busy');
  }
});
