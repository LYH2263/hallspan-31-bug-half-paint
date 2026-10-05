export class ApiError extends Error {
  status: number
  body: any
  constructor(status: number, body: any) {
    super(typeof body === 'string' ? body : JSON.stringify(body))
    this.status = status
    this.body = body
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    let body: any = text
    try { body = JSON.parse(text) } catch { /* 保留原文 */ }
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

/** 把后端错误（detail 为字符串或消息列表）展平成逐条消息，绝不在前端并句。 */
export function errorMessages(e: any): string[] {
  const d = e?.body?.detail
  if (Array.isArray(d)) return d.map(String)
  if (d != null) return [String(d)]
  return [String(e?.message || e)]
}
