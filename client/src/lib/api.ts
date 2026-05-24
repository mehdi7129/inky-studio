export interface HealthResponse {
  status: string
  version: string
}

export interface DisplayState {
  model: string
  width: number
  height: number
  colors: number
  color_mode: 'pimoroni' | 'spectra_palette' | 'warmth_boost'
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

export interface UploadResponse {
  photo: Photo
  queue_entry: QueueEntry
  already_existed: boolean
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} on ${path}`)
  }
  return response.json() as Promise<T>
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJSON<HealthResponse>('/api/health')
}

export function fetchDisplayState(): Promise<DisplayState> {
  return getJSON<DisplayState>('/api/display')
}

export function fetchQueue(): Promise<QueueEntry[]> {
  return getJSON<QueueEntry[]>('/api/queue')
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
