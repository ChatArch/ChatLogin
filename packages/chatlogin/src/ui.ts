import { ChatLoginHTTPError, ChatLoginNetworkError, ChatLoginProtocolError } from './client.js';

/** Shared by the Python default page controller and optional React components. */
export const uiTokens = {
  palettes: ['indigo', 'forest', 'amber'], layouts: ['card', 'split'], appearances: ['system', 'light', 'dark'],
} as const;
export type Language = 'zh-CN' | 'en';
export const labels = {
  'zh-CN': { eyebrow: '欢迎回来', title: 'ChatLogin', subtitle: '登录后继续。', username: '账号', password: '密码',
    login: '登录', loggingIn: '正在登录…', logout: '退出登录', loggingOut: '正在退出…', settings: '账号设置',
    profile: '我的账号', users: '用户管理', guest: '访客', guestContinue: '以访客身份继续', loading: '正在加载账号…', retry: '重试',
    invalid: '登录失败，请检查账号或密码。', rate: '登录尝试过于频繁，请稍后重试。',
    changed: '会话已变化，请重新尝试。', network: '网络连接失败或超时，请检查网络后重试。',
    protocol: '登录服务响应异常，请稍后重试。', service: '登录服务暂时不可用，请稍后重试。' },
  en: { eyebrow: 'Welcome back', title: 'ChatLogin', subtitle: 'Sign in to continue.', username: 'Account', password: 'Password',
    login: 'Sign in', loggingIn: 'Signing in…', logout: 'Sign out', loggingOut: 'Signing out…', settings: 'Account settings',
    profile: 'My profile', users: 'Manage users', guest: 'Guest', guestContinue: 'Continue as guest', loading: 'Loading account…', retry: 'Retry',
    invalid: 'Sign-in failed. Check your account and password.', rate: 'Too many attempts. Please try again later.',
    changed: 'The session changed. Please try again.', network: 'The connection failed or timed out. Please try again.',
    protocol: 'The login service returned an invalid response. Please try again later.', service: 'The login service is unavailable. Please try again later.' },
} as const;

export function loginMessage(error: unknown, language: Language = 'zh-CN'): string {
  const text = labels[language];
  if (error instanceof ChatLoginHTTPError) {
    if (error.status === 401) return text.invalid;
    if (error.status === 429) return text.rate;
    if (error.status === 403) return text.changed;
  }
  if (error instanceof ChatLoginNetworkError) return text.network;
  if (error instanceof ChatLoginProtocolError) return text.protocol;
  return text.service;
}
