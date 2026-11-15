export type SSEHandler = (event: string, data: any) => void

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

/** POST (or GET) a request and consume a text/event-stream response. Resolves when the stream ends. */
export async function streamSSE(
  url: string,
  opts: { method?: 'GET' | 'POST', body?: unknown, signal?: AbortSignal, onEvent: SSEHandler },
  retried = false
): Promise<boolean> {
  const res = await fetch(url, {
    method: opts.method ?? 'POST',
    credentials: 'include',
    headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal
  })
  if (res.status === 401 && !retried) {
    if (await refreshSession()) return streamSSE(url, opts, true)
    useAuthStore().clear()
    await navigateTo('/login')
    throw new HttpError(401, 'Session expired')
  }
  if (res.status === 204) return false
  if (!res.ok || !res.body) {
    let msg = `Request failed (${res.status})`
    try {
      const j = await res.json()
      if (typeof j?.detail === 'string') msg = j.detail
    } catch { /* not json */ }
    throw new HttpError(res.status, msg)
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data.push(line.slice(6))
      }
      if (!data.length) continue // comments / pings
      try {
        opts.onEvent(event, JSON.parse(data.join('\n')))
      } catch (e) {
        console.error('bad SSE frame', e)
      }
    }
  }
  return true
}
