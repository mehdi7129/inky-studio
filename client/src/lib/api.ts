export type ColorModeApi = 'pimoroni' | 'spectra_palette' | 'warmth_boost'
export type ChangeModeApi = 'daily' | 'interval' | 'manual'

export interface HealthResponse {
  status: string
  version: string
}

export interface DisplayInfo {
  model: string
  width: number
  height: number
  colors: number
  color_mode: ColorModeApi
  is_mock: boolean
}

export interface Photo {
  id: string
  sha256: string
  original_filename: string
  mime: string
  width: number
  height: number
  size_bytes: number
  created_at: number
}

export interface QueueEntry {
  id: number
  position: number
  added_at: number
  photo: Photo
}

export interface HistoryEntry {
  id: number
  displayed_at: number
  source: 'auto' | 'manual_next' | 'manual_previous' | 'recycle' | 'upload'
  photo: Photo
}

export interface Settings {
  color_mode: ColorModeApi
  change_mode: ChangeModeApi
  change_hour: number
  change_interval_minutes: number
}

export interface DisplayState {
  display: DisplayInfo
  current: HistoryEntry | null
  queue_count: number
  next_change_at: number | null
}

export interface UploadResponse {
  photo: Photo
  queue_entry: QueueEntry
  already_existed: boolean
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: 'include' })
  if (!response.ok) throw new Error(`HTTP ${response.status} on ${path}`)
  return response.json() as Promise<T>
}

async function sendJSON<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${method} ${path} → ${response.status}: ${detail}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export interface AuthStatus {
  authenticated: boolean
  auth_required: boolean
}

export function fetchAuthStatus(): Promise<AuthStatus> {
  return getJSON('/api/auth/status')
}

export function login(password: string): Promise<AuthStatus> {
  return sendJSON('POST', '/api/auth/login', { password })
}

export function logout(): Promise<AuthStatus> {
  return sendJSON('POST', '/api/auth/logout')
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJSON('/api/health')
}

export function fetchDisplayInfo(): Promise<DisplayInfo> {
  return getJSON('/api/display')
}

export function fetchState(): Promise<DisplayState> {
  return getJSON('/api/state')
}

export function fetchQueue(): Promise<QueueEntry[]> {
  return getJSON('/api/queue')
}

export function fetchHistory(limit = 100, offset = 0): Promise<HistoryEntry[]> {
  return getJSON(`/api/history?limit=${limit}&offset=${offset}`)
}

export function fetchSettings(): Promise<Settings> {
  return getJSON('/api/settings')
}

export function updateSettings(patch: Partial<Settings>): Promise<Settings> {
  return sendJSON('POST', '/api/settings', patch)
}

export function reorderQueue(photoIds: string[]): Promise<QueueEntry[]> {
  return sendJSON('POST', '/api/queue/reorder', { photo_ids: photoIds })
}

export function removeFromQueue(photoId: string): Promise<void> {
  return sendJSON('DELETE', `/api/queue/${photoId}`)
}

export function triggerNext(): Promise<void> {
  return sendJSON('POST', '/api/display/next')
}

export function triggerPrevious(): Promise<void> {
  return sendJSON('POST', '/api/display/previous')
}

export async function uploadToQueue(pngBlob: Blob, filename: string): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', pngBlob, filename)
  const response = await fetch('/api/queue', {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`Upload failed (${response.status}): ${detail}`)
  }
  return response.json() as Promise<UploadResponse>
}

export function photoFileUrl(photoId: string): string {
  return `/api/photos/${photoId}`
}
