import type { ReactNode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueuePanel } from '../components/QueuePanel'
import { ConverterPanel } from '../components/ConverterPanel'
import { SettingsPanel } from '../components/SettingsPanel'
import { HistoryPanel } from '../components/HistoryPanel'
import { Dashboard } from '../components/Dashboard'
import App from '../App'
import * as api from '../lib/api'
import * as pipeline from '../lib/converter/pipeline'
import type { ConvertResult } from '../lib/converter/pipeline'
import type { DisplayState, QueueEntry } from '../lib/api'
import type { EventMessage } from '../lib/useWebSocket'

type DragHandler = (event: { active: { id: string }; over: { id: string } }) => Promise<void>
const handlers = vi.hoisted(() => ({
  drag: undefined as DragHandler | undefined,
  events: [] as ((event: EventMessage) => void)[],
}))

// Exercise queue state through the same onDragEnd callback as dnd-kit, without
// depending on jsdom's lack of pointer hit testing and layout measurements.
vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ onDragEnd, children }: { onDragEnd: DragHandler; children: ReactNode }) => {
    handlers.drag = onDragEnd
    return children
  },
  closestCenter: vi.fn(),
  KeyboardSensor: vi.fn(),
  PointerSensor: vi.fn(),
  useSensor: vi.fn(),
  useSensors: vi.fn(),
}))
vi.mock('@dnd-kit/sortable', async (importOriginal) => ({
  ...await importOriginal<typeof import('@dnd-kit/sortable')>(),
  SortableContext: ({ children }: { children: ReactNode }) => children,
  useSortable: () => ({
    attributes: {}, listeners: {}, setNodeRef: vi.fn(),
    transform: null, transition: null, isDragging: false,
  }),
}))
vi.mock('../lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../lib/api')>(),
  reorderQueue: vi.fn(), removeFromQueue: vi.fn(), uploadToQueue: vi.fn(),
  fetchSettings: vi.fn(), updateSettings: vi.fn(), fetchUpdateStatus: vi.fn(),
  startUpdate: vi.fn(), fetchHealth: vi.fn(), fetchAuthStatus: vi.fn(),
  fetchState: vi.fn(), fetchQueue: vi.fn(), logout: vi.fn(), fetchHistory: vi.fn(),
  clearHistory: vi.fn(), deleteHistoryEntry: vi.fn(), triggerNext: vi.fn(), triggerPrevious: vi.fn(),
}))
vi.mock('../lib/converter/pipeline', () => ({ decode: vi.fn(), convertBitmap: vi.fn() }))
vi.mock('../components/PreviewCanvas', () => ({ PreviewCanvas: () => null }))
vi.mock('../lib/useWebSocket', () => ({
  useWebSocket: (handler: (event: EventMessage) => void) => { handlers.events.push(handler) },
}))

const display = { width: 800, height: 480, colors: 7, model: 'Mock', is_mock: true }
const settings = { change_mode: 'manual' as const, change_hour: 8, change_interval_minutes: 60, saturation: 1 }
const state: DisplayState = { display, current: null, queue_count: 0, next_change_at: null }
const entry = (id: string): QueueEntry => ({
  id: id.charCodeAt(0), position: 0, added_at: 0,
  photo: {
    id, original_filename: id + '.png', sha256: id, mime: 'image/png',
    width: 800, height: 480, size_bytes: 1, created_at: 0,
  },
})
const conversion = (content: string): ConvertResult => ({
  originalImage: {} as ImageData, pngBlob: new Blob([content]), durationMs: 1, wasHeic: false,
})

async function mountApp() {
  vi.mocked(api.fetchAuthStatus).mockResolvedValue({ authenticated: true, auth_required: false })
  vi.mocked(api.fetchHealth).mockResolvedValue({ version: '1', status: 'ok' })
  vi.mocked(api.fetchState).mockResolvedValue(state)
  vi.mocked(api.fetchQueue).mockResolvedValue([])
  render(<App />)
  await screen.findByRole('button', { name: 'Tableau de bord' })
  return handlers.events.at(-1)!
}

beforeEach(() => {
  vi.resetAllMocks()
  handlers.events = []
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(cleanup)

describe('UI stability regressions', () => {
  it.each([
    [{ code: 2, message: 'Impossible de lire cette photo HEIC.' }, 'Impossible de lire cette photo HEIC.'],
    [{ code: 2 }, 'Impossible de lire cette photo. Essayez un fichier JPEG ou PNG.'],
  ])('shows a readable decoder error and prevents uploading on failure (%j)', async (error, message) => {
    vi.mocked(pipeline.decode).mockRejectedValue(error)
    render(<ConverterPanel file={new File(['x'], 'photo.HEIC')} display={display} onUploaded={() => {}} onReset={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.queryByText(/\[object Object\]/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: "Envoyer à l'écran" })).toBeDisabled()
    expect(pipeline.convertBitmap).not.toHaveBeenCalled()
    expect(api.uploadToQueue).not.toHaveBeenCalled()
  })

  it('shows new queue entries and remote order after a successful reorder', async () => {
    vi.mocked(api.reorderQueue).mockResolvedValue([entry('b'), entry('a')])
    const { rerender } = render(<QueuePanel queue={[entry('a'), entry('b')]} onChange={() => {}} />)
    await act(async () => { await handlers.drag!({ active: { id: 'a' }, over: { id: 'b' } }) })
    rerender(<QueuePanel queue={[entry('c'), entry('a'), entry('b')]} onChange={() => {}} />)
    expect(screen.getAllByRole('img').map((image) => image.getAttribute('alt')))
      .toEqual(['c.png', 'a.png', 'b.png'])
  })

  it('blocks stale crop uploads, then uploads the completed current crop', async () => {
    vi.mocked(pipeline.decode).mockResolvedValue({
      bitmap: { width: 800, height: 480, close: vi.fn() } as unknown as ImageBitmap,
      width: 800, height: 480, sourceFilename: 'a.png', wasHeic: false,
    })
    let finishCrop!: (result: ConvertResult) => void
    vi.mocked(pipeline.convertBitmap)
      .mockResolvedValueOnce(conversion('old'))
      .mockReturnValueOnce(new Promise((resolve) => { finishCrop = resolve }))
    render(<ConverterPanel file={new File(['x'], 'a.png')} display={display} onUploaded={() => {}} onReset={() => {}} />)
    const upload = screen.getByRole('button', { name: "Envoyer à l'écran" })
    await waitFor(() => expect(upload).toBeEnabled())
    fireEvent.change(screen.getAllByRole('slider')[0], { target: { value: '0.5' } })
    expect(upload).toBeDisabled()
    fireEvent.click(upload)
    expect(api.uploadToQueue).not.toHaveBeenCalled()
    const latest = conversion('new')
    await act(async () => { finishCrop(latest) })
    expect(upload).toBeEnabled()
    fireEvent.click(upload)
    await waitFor(() => expect(api.uploadToQueue).toHaveBeenCalledWith(latest.pngBlob, 'a.png'))
  })

  it('shows failure of an explicit update check', async () => {
    vi.mocked(api.fetchSettings).mockResolvedValue(settings)
    vi.mocked(api.fetchUpdateStatus).mockRejectedValue(new Error('GitHub unreachable'))
    render(<SettingsPanel onChange={() => {}} health={{ version: '1', status: 'ok' }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Vérifier les mises à jour' }))
    expect(await screen.findByText(/GitHub unreachable/)).toBeInTheDocument()
  })

  it('resynchronizes state after a WebSocket reconnect hello', async () => {
    const onEvent = await mountApp()
    const calls = vi.mocked(api.fetchState).mock.calls.length
    await act(async () => { onEvent({ type: 'hello' }) })
    expect(api.fetchState).toHaveBeenCalledTimes(calls + 1)
  })

  it('refreshes an already open history tab after a remote display change', async () => {
    const onEvent = await mountApp()
    vi.mocked(api.fetchHistory).mockResolvedValueOnce([]).mockResolvedValueOnce([
      { id: 1, displayed_at: 1, source: 'auto', photo: entry('a').photo },
    ])
    fireEvent.click(screen.getByRole('button', { name: 'Historique' }))
    await screen.findByText("Aucun historique pour l'instant")
    await act(async () => { onEvent({ type: 'display_changed' }) })
    expect(await screen.findByText('a.png')).toBeInTheDocument()
  })

  it('refreshes settings from another client while the tab remains open', async () => {
    const onEvent = await mountApp()
    vi.mocked(api.fetchSettings).mockResolvedValueOnce(settings).mockResolvedValueOnce({ ...settings, saturation: 1.5 })
    vi.mocked(api.fetchUpdateStatus).mockResolvedValue({ current: '1', latest: '1', update_available: false })
    fireEvent.click(screen.getByRole('button', { name: 'Paramètres' }))
    expect(await screen.findByRole('slider')).toHaveValue('1')
    await act(async () => { onEvent({ type: 'settings_changed' }) })
    await waitFor(() => expect(screen.getByRole('slider')).toHaveValue('1.5'))
  })

  it('does not replace a fresh state with an older overlapping refresh', async () => {
    const onEvent = await mountApp()
    let finishOld!: (value: DisplayState) => void
    vi.mocked(api.fetchState)
      .mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve }))
      .mockResolvedValueOnce({ ...state, display: { ...display, model: 'New panel' } })
    await act(async () => { onEvent({ type: 'queue_updated' }); onEvent({ type: 'queue_updated' }) })
    expect(screen.getAllByText(/New panel/).length).toBeGreaterThan(0)
    await act(async () => { finishOld(state) })
    expect(screen.getAllByText(/New panel/).length).toBeGreaterThan(0)
  })

  it('returns to login when resynchronization finds an expired session', async () => {
    const onEvent = await mountApp()
    vi.mocked(api.fetchState).mockRejectedValueOnce(new api.ApiError(401, 'Expired session'))
    await act(async () => { onEvent({ type: 'hello' }) })
    expect(await screen.findByRole('button', { name: 'Se connecter' })).toBeInTheDocument()
  })

  it('shows display navigation errors instead of silently rejecting', async () => {
    vi.mocked(api.triggerNext).mockRejectedValue(new Error('Display unavailable'))
    render(<Dashboard state={state} queue={[]} onChange={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Afficher la suivante' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Display unavailable')
    expect(screen.getByRole('button', { name: 'Afficher la suivante' })).toBeEnabled()
  })
})

it('keeps newer saved settings when an older event read completes', async () => {
  let finishOld!: (value: typeof settings) => void
  vi.mocked(api.fetchSettings).mockResolvedValueOnce(settings)
    .mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve }))
  vi.mocked(api.fetchUpdateStatus).mockResolvedValue({ current: '1', latest: '1', update_available: false })
  vi.mocked(api.updateSettings).mockResolvedValue({ ...settings, saturation: 1.5 })
  const { rerender } = render(<SettingsPanel revision={0} onChange={() => {}} health={null} />)
  const slider = await screen.findByRole('slider')
  rerender(<SettingsPanel revision={1} onChange={() => {}} health={null} />)
  fireEvent.change(slider, { target: { value: '1.5' } })
  fireEvent.pointerUp(slider)
  await screen.findByText('✓ Enregistré')
  expect(slider).toHaveValue('1.5')
  await act(async () => { finishOld(settings) })
  expect(slider).toHaveValue('1.5')
})

it('keeps fresh history when a prior mutation reload completes', async () => {
  const historyEntry = (id: string) => ({ id: id.charCodeAt(0), displayed_at: 1, source: 'auto' as const, photo: entry(id).photo })
  const a = historyEntry('a'), b = historyEntry('b'), c = historyEntry('c')
  let finishOld!: (value: typeof a[]) => void
  vi.mocked(api.fetchHistory).mockResolvedValueOnce([a,b])
    .mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve }))
    .mockResolvedValueOnce([c,b])
  vi.mocked(api.deleteHistoryEntry).mockResolvedValue(undefined)
  const { rerender } = render(<HistoryPanel revision={0} onChange={() => {}} />)
  await screen.findByText('a.png')
  fireEvent.click(screen.getAllByTitle("Supprimer de l'historique")[0])
  await waitFor(() => expect(api.fetchHistory).toHaveBeenCalledTimes(2))
  rerender(<HistoryPanel revision={1} onChange={() => {}} />)
  await screen.findByText('c.png')
  await act(async () => { finishOld([b]) })
  expect(screen.queryByText('c.png')).toBeInTheDocument()
})
