import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { accountLinks, publicSession, safeNext } from './client.js';
import type { ChatLoginClient, Discovery, Principal, PublicSession } from './client.js';
import { labels, loginMessage } from './ui.js';
import type { Language, uiTokens } from './ui.js';

export interface LoginFormProps {
  client: ChatLoginClient;
  title?: string;
  subtitle?: string;
  eyebrow?: string;
  language?: Language;
  palette?: typeof uiTokens.palettes[number];
  layout?: typeof uiTokens.layouts[number];
  appearance?: typeof uiTokens.appearances[number];
  className?: string;
  next?: string;
  guestUrl?: string;
  guestLabel?: string;
  /** No password/CSRF reaches UI callbacks. Without this, navigate locally. */
  onSuccess?: (result: { user: Principal; next: string }) => void;
  onError?: (error: unknown) => void;
}

export function LoginForm(props: LoginFormProps): ReactNode {
  const language = props.language ?? 'zh-CN', text = labels[language];
  const [busy, setBusy] = useState(false), [status, setStatus] = useState('');
  const pending = useRef(false), active = useRef<AbortController | null>(null), revision = useRef(0);
  useEffect(() => {
    ++revision.current; pending.current = false; setBusy(false); setStatus('');
    return () => { ++revision.current; active.current?.abort(); };
  }, [props.client]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    const form = event.currentTarget;
    const username = form.elements.namedItem('username') as HTMLInputElement;
    const password = form.elements.namedItem('password') as HTMLInputElement;
    const input = { username: username.value, password: password.value, next: safeNext(props.next) };
    // Credentials stay in uncontrolled inputs/request memory, never React state.
    password.value = '';
    pending.current = true; setBusy(true); setStatus(text.loggingIn);
    const generation = ++revision.current, controller = new AbortController(); active.current = controller;
    try {
      const result = await props.client.login(input, { signal: controller.signal });
      if (generation !== revision.current || controller.signal.aborted) return;
      setStatus('');
      if (props.onSuccess) props.onSuccess({ user: result.user, next: result.next });
      else window.location.assign(result.next);
    } catch (error) {
      if (generation !== revision.current || controller.signal.aborted) return;
      setStatus(loginMessage(error, language)); props.onError?.(error);
    } finally {
      if (generation === revision.current) { pending.current = false; setBusy(false); }
    }
  }

  const guestUrl = props.guestUrl === undefined ? undefined : safeNext(props.guestUrl);
  if (props.guestUrl !== undefined && guestUrl !== props.guestUrl) throw new TypeError('guestUrl must be a safe local path');
  return <section className={['chatlogin', props.className].filter(Boolean).join(' ')}
    data-palette={props.palette ?? 'indigo'} data-layout={props.layout ?? 'card'} data-appearance={props.appearance ?? 'system'}>
    <section className="chatlogin__panel">
      <div className="chatlogin__branding"><p className="chatlogin__eyebrow">{props.eyebrow ?? text.eyebrow}</p>
        <h1>{props.title ?? text.title}</h1><p className="chatlogin__subtitle">{props.subtitle ?? text.subtitle}</p></div>
      <div className="chatlogin__form-panel">
        <form className="chatlogin__form" method="post" action={props.client.basePath + '/login'} onSubmit={submit} aria-busy={busy || undefined}>
          <input type="hidden" name="next" value={safeNext(props.next)} />
          <label><span>{text.username}</span><input name="username" autoComplete="username" required maxLength={256} /></label>
          <label><span>{text.password}</span><input name="password" type="password" autoComplete="current-password" required maxLength={1024} /></label>
          <button type="submit" disabled={busy}>{text.login}</button>
          <p className="chatlogin__status" role="status" aria-live="polite" aria-atomic="true">{status}</p>
        </form>
        {guestUrl !== undefined && <a className="chatlogin__guest" href={guestUrl}>{props.guestLabel ?? text.guestContinue}</a>}
      </div>
    </section>
  </section>;
}

export interface AccountMenuProps {
  client: ChatLoginClient;
  language?: Language;
  mode?: 'gear' | 'links';
  /** Change after host-initiated login/account changes or expired-session handling. */
  refreshKey?: unknown;
  onLogout?: () => void;
  onError?: (error: unknown) => void;
}
type View = { manifest: Discovery; session: PublicSession };

export function AccountMenu(props: AccountMenuProps): ReactNode {
  const language = props.language ?? 'zh-CN', text = labels[language], mode = props.mode ?? 'gear';
  const [view, setView] = useState<View | null>(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [refresh, setRefresh] = useState(0);
  const revision = useRef(0), pending = useRef(false), active = useRef<AbortController | null>(null);
  const onError = useRef(props.onError); onError.current = props.onError;

  useEffect(() => {
    const generation = ++revision.current, controller = new AbortController();
    active.current?.abort(); active.current = controller;
    pending.current = false; setBusy(false); setError(''); setView(null);
    Promise.all([props.client.discover({ signal: controller.signal }), props.client.session({ signal: controller.signal })])
      .then(([manifest, session]) => {
        if (generation === revision.current && !controller.signal.aborted) setView({ manifest, session: publicSession(session) });
      }).catch(cause => {
        if (generation === revision.current && !controller.signal.aborted) { setError(loginMessage(cause, language)); onError.current?.(cause); }
      });
    return () => { ++revision.current; controller.abort(); active.current?.abort(); };
  }, [props.client, props.refreshKey, refresh, language]);

  async function logout() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    const generation = ++revision.current, controller = new AbortController();
    active.current?.abort(); active.current = controller;
    try {
      await props.client.logout({ signal: controller.signal });
      if (generation !== revision.current || controller.signal.aborted) return;
      if (view) setView({ manifest: view.manifest, session: { authenticated: false, user: null } });
      props.onLogout?.();
    } catch (cause) {
      if (generation !== revision.current || controller.signal.aborted) return;
      setError(loginMessage(cause, language)); onError.current?.(cause);
    } finally {
      if (generation === revision.current) { pending.current = false; setBusy(false); }
    }
  }

  if (!view) return <nav className="chatlogin-account-menu" aria-label={text.settings}>
    <span className="chatlogin-account-menu__status" role="status">{error || text.loading}</span>
    {error && <button type="button" className="chatlogin-account-menu__link" onClick={() => setRefresh(value => value + 1)}>{text.retry}</button>}
  </nav>;
  const content = <>
    <span className="chatlogin-account-menu__identity">{view.session.authenticated ? view.session.user.display_name || view.session.user.user_id : text.guest}</span>
    {accountLinks(view.manifest, view.session).map(link => <a key={link.key} className="chatlogin-account-menu__link" href={link.url}>{text[link.key]}</a>)}
    {view.session.authenticated && <button type="button" className="chatlogin-account-menu__link" onClick={logout} disabled={busy}>{busy ? text.loggingOut : text.logout}</button>}
    {error && <span className="chatlogin-account-menu__status" role="alert">{error}</span>}
  </>;
  return <nav className={'chatlogin-account-menu chatlogin-account-menu--' + mode} aria-label={text.settings} aria-busy={busy || undefined}>
    {mode === 'gear' ? <details><summary aria-label={text.settings} title={text.settings}><span aria-hidden="true">⚙</span><span>{text.settings}</span></summary>
      <div className="chatlogin-account-menu__panel">{content}</div></details> : content}
  </nav>;
}
