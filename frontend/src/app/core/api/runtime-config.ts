type AppRuntimeConfig = {
  API_BASE_URL?: string;
};

declare global {
  interface Window {
    __APP_CONFIG__?: AppRuntimeConfig;
  }
}

function normalizeApiBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    return '/api';
  }

  const normalized = trimmed.replace(/\/+$/, '');
  return normalized === '/' ? '' : normalized;
}

export function getApiBaseUrl(): string {
  if (typeof window === 'undefined') {
    return '/api';
  }
  return normalizeApiBaseUrl(window.__APP_CONFIG__?.API_BASE_URL);
}
