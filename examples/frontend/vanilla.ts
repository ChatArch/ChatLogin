/** Browser-only host example. Its Python auth routes remain the authority. */
import { createChatLoginClient, ChatLoginHTTPError } from '@chatarch/chatlogin';

const auth = createChatLoginClient({ basePath: '/auth' });
const form = document.querySelector<HTMLFormElement>('#sign-in');
const status = document.querySelector<HTMLElement>('#sign-in-status');

form?.addEventListener('submit', async event => {
  event.preventDefault();
  const username = form.elements.namedItem('username') as HTMLInputElement;
  const password = form.elements.namedItem('password') as HTMLInputElement;
  const input = { username: username.value, password: password.value, next: '/workspace' };
  password.value = '';
  try {
    const result = await auth.login(input);
    window.location.assign(result.next);
  } catch (error) {
    if (status) status.textContent = error instanceof ChatLoginHTTPError && error.status === 401
      ? 'Check your account and password.' : 'Sign-in did not complete. Please retry.';
  }
});

document.querySelector('#sign-out')?.addEventListener('click', async () => {
  await auth.logout(); // failure keeps the current page; do not claim revocation
  window.location.assign('/auth/');
});
