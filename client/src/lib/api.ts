export interface HealthResponse {
  status: string
  version: string
}

export interface DisplayState {
  model: string
  width: number
  height: number
  colors: number
  color_mode: string
  is_mock: boolean
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
