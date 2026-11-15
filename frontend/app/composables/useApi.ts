let refreshing: Promise<boolean> | null = null

/** Try to renew the access cookie with the refresh cookie (deduplicated). */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = $fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        setTimeout(() => { refreshing = null }, 0)
      })
  }
  return refreshing
}

export function errorMessage(e: unknown, fallback = 'Something went wrong'): string {
  const err = e as { data?: { detail?: unknown }, message?: string }
  const detail = err?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return `${detail[0].loc?.slice(-1)[0] ?? 'field'}: ${detail[0].msg}`
  return err?.message || fallback
}

interface ApiOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: Record<string, unknown> | unknown[]
  query?: Record<string, string | number | boolean | undefined>
  _retry?: boolean
}

/** $fetch with cookies, transparent token refresh and redirect to /login on expiry. */
export async function api<T = unknown>(url: string, opts: ApiOptions = {}): Promise<T> {
  try {
    const { _retry, ...rest } = opts
    return await $fetch<T>(url, { credentials: 'include', ...rest }) as T
  } catch (e: unknown) {
    const status = (e as { statusCode?: number })?.statusCode
    if (status === 401 && !opts._retry && !url.startsWith('/api/auth/')) {
      if (await refreshSession()) return api<T>(url, { ...opts, _retry: true })
      useAuthStore().clear()
      await navigateTo('/login')
    }
    throw e
  }
}
