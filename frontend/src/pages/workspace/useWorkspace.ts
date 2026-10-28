import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { FileInfo } from '../../components/FileTable'
import { ApiError, apiJson, authFetch as fetch, chunkedUpload, getUploadConfig } from '../../utils/api'
import { downloadBlob, downloadFile } from '../../utils/download'
import {
  createPreset,
  getCapabilities,
  listPresets,
  probeFile,
  type Capabilities,
  type EncodeOptions,
  type Preset,
} from '../../utils/encoding'
import { stripExtension } from '../../utils/filename'
import {
  cancelCompressionJob,
  cancelJob,
  createCompressionJob,
  createJob,
  listCompressionJobs,
  listJobs,
  type CompressionJob,
  type ConversionJob,
} from '../../utils/jobs'
import {
  EMPTY_DEFAULTS,
  buildRequest,
  convertFormats,
  isActionable,
  isActive,
  isCompressible,
  isReady,
  makeItem,
  sortCompressionLevels,
  targetInfo,
  usesAdvancedPath,
  withOutput,
  type ItemResult,
  type JobKind,
  type WorkspaceDefaults,
  type WorkspaceItem,
} from './model'

const POLL_INTERVAL_MS = 1500

type AnyJob = ConversionJob | CompressionJob

async function responseDetail(response: Response): Promise<string> {
  try {
    const data = await response.json()
    if (typeof data?.detail === 'string') return data.detail
    if (Array.isArray(data?.detail) && typeof data.detail[0]?.msg === 'string') return data.detail[0].msg
  } catch { /* not JSON */ }
  return response.statusText
}

function toFileInfo(meta: FileInfo): FileInfo {
  return {
    id: meta.id,
    original_filename: meta.original_filename,
    media_type: meta.media_type,
    extension: meta.extension,
    size_bytes: meta.size_bytes,
    created_at: meta.created_at,
    compatible_formats: meta.compatible_formats,
  }
}

function mergeOptions(base: EncodeOptions | undefined, own: EncodeOptions): EncodeOptions {
  const merged: Record<string, unknown> = { ...(base ?? {}) }
  for (const [key, value] of Object.entries(own)) {
    const prev = merged[key]
    merged[key] = value && typeof value === 'object' && prev && typeof prev === 'object'
      ? { ...(prev as object), ...(value as object) }
      : value
  }
  return merged as EncodeOptions
}

export function useWorkspace() {
  const { t } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()

  const [items, setItems] = useState<WorkspaceItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [defaults, setDefaults] = useState<WorkspaceDefaults>(EMPTY_DEFAULTS)
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [presets, setPresets] = useState<Preset[]>([])
  const [uploadCount, setUploadCount] = useState(0)
  const [ignoredCount, setIgnoredCount] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [autoDownload, setAutoDownload] = useState(false)
  const [chunkSize, setChunkSize] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [downloadingAll, setDownloadingAll] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  const itemsRef = useRef(items)
  const defaultsRef = useRef(defaults)
  const autoDownloadRef = useRef(autoDownload)
  const chunkSizeRef = useRef(chunkSize)
  useEffect(() => { itemsRef.current = items }, [items])
  useEffect(() => { defaultsRef.current = defaults }, [defaults])
  useEffect(() => { autoDownloadRef.current = autoDownload }, [autoDownload])
  useEffect(() => { chunkSizeRef.current = chunkSize }, [chunkSize])

  const updateItem = useCallback((id: string, update: (item: WorkspaceItem) => WorkspaceItem) => {
    setItems(prev => prev.map(item => (item.file.id === id ? update(item) : item)))
  }, [])

  // ── defaults and capabilities ────────────────────────────────────

  useEffect(() => {
    fetch('/api/settings')
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(data => setAutoDownload(!!data.auto_download))
      .catch(() => {})
    fetch('/api/default-formats')
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then((data: { defaults: { input_format: string; output_format: string }[]; aliases: Record<string, string> }) => {
        const map: Record<string, string> = {}
        for (const d of data.defaults) map[d.input_format] = d.output_format
        setDefaults(prev => ({ ...prev, defaultFormats: map, aliases: data.aliases || {} }))
      })
      .catch(() => {})
    fetch('/api/default-qualities')
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then((data: { defaults: { output_format: string; quality: string }[] }) => {
        const map: Record<string, string> = {}
        for (const d of data.defaults) map[d.output_format] = d.quality
        setDefaults(prev => ({ ...prev, defaultQualities: map }))
      })
      .catch(() => {})
    fetch('/api/compressors')
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then((data: { compressors: { supported_formats: string[]; formats_with_compression_levels: string[]; compression_levels: string[] }[] }) => {
        const levels: Record<string, Set<string>> = {}
        const compressible = new Set<string>()
        for (const c of data.compressors) {
          for (const fmt of c.supported_formats) {
            compressible.add(fmt)
            levels[fmt] ??= new Set()
          }
          for (const fmt of c.formats_with_compression_levels) {
            levels[fmt] ??= new Set()
            for (const level of c.compression_levels) levels[fmt].add(level)
          }
        }
        const byFormat: Record<string, string[]> = {}
        for (const [fmt, set] of Object.entries(levels)) byFormat[fmt] = sortCompressionLevels([...set])
        setDefaults(prev => ({ ...prev, compressionLevelsByFormat: byFormat, compressibleFormats: compressible }))
      })
      .catch(() => {})
    fetch('/api/default-compression-levels')
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then((data: { defaults: { media_format: string; compression_level: string }[] }) => {
        const map: Record<string, string> = {}
        for (const d of data.defaults) map[d.media_format] = d.compression_level
        setDefaults(prev => ({ ...prev, defaultCompressionLevels: map }))
      })
      .catch(() => {})
    getUploadConfig().then(data => setChunkSize(data.max_chunk_size)).catch(() => {})
    getCapabilities().then(setCaps).catch(() => {})
    listPresets().then(setPresets).catch(() => {})
  }, [])

  // ── adding files ─────────────────────────────────────────────────

  const addFiles = useCallback((files: FileInfo[]) => {
    const current = defaultsRef.current
    const accepted = files.filter(file => isActionable(file, current))
    const ignored = files.length - accepted.length
    if (ignored > 0) setIgnoredCount(prev => prev + ignored)
    if (accepted.length === 0) return
    setItems(prev => [...prev, ...accepted.map(file => makeItem(file, current))])
    setSelectedId(prev => prev ?? accepted[0].id)
    for (const file of accepted) {
      probeFile(file.id)
        .then(probe => updateItem(file.id, item => ({ ...item, probe })))
        .catch(() => updateItem(file.id, item => ({ ...item, probe: null })))
    }
  }, [updateItem])

  // Files handed over from the Files page.
  useEffect(() => {
    if (location.state?.files) {
      addFiles(location.state.files as FileInfo[])
      navigate(location.pathname, { replace: true })
    }
  }, [location.state, location.pathname, navigate, addFiles])

  const uploadFiles = useCallback(async (files: File[]) => {
    if (files.length === 0) return
    setError(null)
    setIgnoredCount(0)
    setUploadCount(prev => prev + files.length)

    const results = await Promise.allSettled(files.map(async (file) => {
      try {
        let data: { metadata: FileInfo }
        const chunk = chunkSizeRef.current
        if (chunk > 0 && file.size > chunk) {
          try {
            data = await chunkedUpload(file, chunk) as { metadata: FileInfo }
          } catch (err) {
            if (err instanceof ApiError && err.status === 422) {
              setIgnoredCount(prev => prev + 1)
              return
            }
            throw err
          }
        } else {
          const formData = new FormData()
          formData.append('file', file)
          const response = await fetch('/api/files', { method: 'POST', body: formData })
          if (!response.ok) {
            if (response.status === 422) {
              setIgnoredCount(prev => prev + 1)
              return
            }
            throw new Error(t('workspace.uploadFailed', { name: file.name, detail: await responseDetail(response) }))
          }
          data = await response.json()
        }
        addFiles([toFileInfo(data.metadata)])
      } finally {
        setUploadCount(prev => Math.max(prev - 1, 0))
      }
    }))

    const errors = results
      .filter((r): r is PromiseRejectedResult => r.status === 'rejected')
      .map(r => (r.reason instanceof Error ? r.reason.message : t('workspace.uploadFailedGeneric')))
    if (errors.length > 0) setError(errors.join('; '))
  }, [addFiles, t])

  const uploadUrl = useCallback(async (url: string) => {
    const trimmed = url.trim()
    if (!trimmed) return false
    setError(null)
    setIgnoredCount(0)
    setUploadCount(prev => prev + 1)
    try {
      const response = await fetch('/api/files/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: trimmed }),
      })
      if (!response.ok) {
        if (response.status === 422) {
          setIgnoredCount(1)
          return false
        }
        throw new Error(await responseDetail(response))
      }
      const data = await response.json()
      const files: FileInfo[] = Array.isArray(data.files) ? data.files.map(toFileInfo) : []
      if (files.length === 0) {
        setIgnoredCount(1)
        return false
      }
      addFiles(files)
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : t('workspace.urlUploadFailed'))
      return false
    } finally {
      setUploadCount(prev => Math.max(prev - 1, 0))
    }
  }, [addFiles, t])

  // ── editing rows ─────────────────────────────────────────────────

  const setOutput = useCallback((id: string, output: string) => {
    updateItem(id, item => withOutput(item, output, defaultsRef.current))
  }, [updateItem])

  const patchItem = useCallback((id: string, patch: Partial<Pick<WorkspaceItem, 'quality' | 'compressionLevel' | 'preset' | 'options'>>) => {
    updateItem(id, item => ({
      ...item,
      ...patch,
      status: isReady(item) ? 'ready' : item.status,
      error: isReady(item) ? undefined : item.error,
    }))
  }, [updateItem])

  /** Copy one row's output and encode settings to every compatible ready row. */
  const applyToAll = useCallback((sourceId: string) => {
    const current = defaultsRef.current
    setItems(prev => {
      const source = prev.find(item => item.file.id === sourceId)
      if (!source) return prev
      const sourcePanel = targetInfo(source, current, caps).panel
      return prev.map(item => {
        if (item.file.id === sourceId || !isReady(item)) return item
        const canTake = source.output ? convertFormats(item.file).includes(source.output) : isCompressible(item.file, current)
        if (!canTake) return item
        const moved = withOutput(item, source.output, current)
        if (targetInfo(moved, current, caps).panel !== sourcePanel) return moved
        return {
          ...moved,
          quality: source.quality && moved.quality !== undefined ? source.quality : moved.quality,
          compressionLevel: source.compressionLevel && moved.compressionLevel !== undefined ? source.compressionLevel : moved.compressionLevel,
          preset: source.preset,
          options: structuredClone(source.options),
        }
      })
    })
  }, [caps])

  const savePreset = useCallback(async (id: string, name: string) => {
    const item = itemsRef.current.find(i => i.file.id === id)
    if (!item) return
    const panel = targetInfo(item, defaultsRef.current, caps).panel
    const base = presets.find(p => p.id === item.preset)?.options
    try {
      const created = await createPreset({
        name,
        kind: panel === 'image' ? 'image' : 'video',
        options: mergeOptions(base, item.options),
      })
      setPresets(prev => [...prev, created])
      patchItem(id, { preset: created.id, options: {} })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('workspace.presetSaveFailed'))
    }
  }, [caps, presets, patchItem, t])

  // ── jobs ─────────────────────────────────────────────────────────

  const fetchResult = useCallback(async (job: AnyJob, kind: JobKind, item: WorkspaceItem): Promise<ItemResult> => {
    const path = kind === 'compress' ? '/api/compressions/complete' : '/api/conversions/complete'
    try {
      const data = await apiJson<Record<string, Array<ItemResult>>>(path)
      const list = data[kind === 'compress' ? 'compressions' : 'conversions'] || []
      const match = list.find(c => c.id === job.output_file_id)
      if (match) return { ...match, encoder_used: match.encoder_used ?? job.encoder_used ?? null }
    } catch { /* fall back to the job payload */ }
    const output = kind === 'convert' ? (job as ConversionJob).output_format : item.file.media_type
    return {
      id: job.output_file_id!,
      original_filename: item.file.original_filename,
      media_type: output,
      extension: kind === 'convert' ? `.${output}` : item.file.extension,
      size_bytes: 0,
      created_at: job.completed_at || new Date().toISOString(),
      encoder_used: job.encoder_used ?? null,
    }
  }, [])

  const download = useCallback(async (item: WorkspaceItem) => {
    if (!item.result) return
    setBusyId(item.file.id)
    try {
      const name = stripExtension(item.file.original_filename || 'download') + (item.result.extension || '')
      await downloadFile(`/api/files/${item.result.id}`, name, chunkSizeRef.current)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('workspace.downloadFailed'))
    } finally {
      setBusyId(null)
    }
  }, [t])

  const applyJob = useCallback(async (job: AnyJob, kind: JobKind) => {
    const item = itemsRef.current.find(i => i.job?.id === job.id)
    if (!item) return
    const id = item.file.id
    if (job.status === 'completed' && job.output_file_id) {
      const result = await fetchResult(job, kind, item)
      updateItem(id, current => ({
        ...current,
        status: 'completed',
        result,
        job: current.job ? { ...current.job, progress: 100, etaSeconds: 0 } : current.job,
      }))
      if (autoDownloadRef.current) await download({ ...item, result })
      return
    }
    if (job.status === 'failed') {
      updateItem(id, current => ({ ...current, status: 'failed', error: job.error_message || t('workspace.status.failed') }))
      return
    }
    if (job.status === 'cancelled') {
      updateItem(id, current => ({ ...current, status: 'cancelled', error: undefined }))
      return
    }
    updateItem(id, current => ({
      ...current,
      status: job.status === 'running' ? 'running' : 'queued',
      job: current.job ? {
        ...current.job,
        progress: job.progress ?? current.job.progress,
        etaSeconds: job.eta_seconds ?? null,
        speed: job.speed ?? null,
      } : current.job,
    }))
  }, [download, fetchResult, t, updateItem])

  const pollOnce = useCallback(async () => {
    const active = itemsRef.current.filter(item => isActive(item) && item.job)
    if (active.length === 0) return
    const kinds = new Set(active.map(item => item.job!.kind))
    try {
      const [conversions, compressions] = await Promise.all([
        kinds.has('convert') ? listJobs() : Promise.resolve([] as ConversionJob[]),
        kinds.has('compress') ? listCompressionJobs() : Promise.resolve([] as CompressionJob[]),
      ])
      const byId = new Map<string, { job: AnyJob; kind: JobKind }>()
      for (const job of conversions) byId.set(job.id, { job, kind: 'convert' })
      for (const job of compressions) byId.set(job.id, { job, kind: 'compress' })
      for (const item of active) {
        const entry = byId.get(item.job!.id)
        if (entry) await applyJob(entry.job, entry.kind)
      }
    } catch {
      // The next tick retries.
    }
  }, [applyJob])

  const hasActive = items.some(isActive)
  useEffect(() => {
    if (!hasActive) return
    const handle = window.setInterval(() => { void pollOnce() }, POLL_INTERVAL_MS)
    return () => window.clearInterval(handle)
  }, [hasActive, pollOnce])

  const submit = useCallback(async (ids?: string[]) => {
    const targets = itemsRef.current.filter(item => isReady(item) && (!ids || ids.includes(item.file.id)))
    if (targets.length === 0) return
    setSubmitting(true)
    setError(null)
    await Promise.allSettled(targets.map(async (item) => {
      const request = buildRequest(item)
      try {
        const job = request.kind === 'compress'
          ? await createCompressionJob(request.body as unknown as Parameters<typeof createCompressionJob>[0])
          : await createJob(request.body as unknown as Parameters<typeof createJob>[0])
        updateItem(item.file.id, current => ({
          ...current,
          status: job.status === 'running' ? 'running' : 'queued',
          error: undefined,
          result: undefined,
          job: {
            id: job.id,
            kind: request.kind,
            progress: job.progress ?? null,
            etaSeconds: null,
            speed: null,
            cancellable: usesAdvancedPath(item),
          },
        }))
      } catch (err) {
        const message = err instanceof Error ? err.message : t('workspace.submitFailed')
        updateItem(item.file.id, current => ({ ...current, status: 'failed', error: message }))
      }
    }))
    setSubmitting(false)
    await pollOnce()
  }, [pollOnce, t, updateItem])

  const cancel = useCallback(async (id: string) => {
    const item = itemsRef.current.find(i => i.file.id === id)
    if (!item?.job) return
    setBusyId(id)
    try {
      const job = item.job.kind === 'compress' ? await cancelCompressionJob(item.job.id) : await cancelJob(item.job.id)
      await applyJob(job, item.job.kind)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('workspace.cancelFailed'))
    } finally {
      setBusyId(null)
    }
  }, [applyJob, t])

  const remove = useCallback(async (id: string) => {
    setBusyId(id)
    try {
      const response = await fetch(`/api/files/${id}`, { method: 'DELETE' })
      if (!response.ok && response.status !== 404) throw new Error(t('workspace.deleteFailed'))
      setItems(prev => prev.filter(item => item.file.id !== id))
      setSelectedId(prev => (prev === id ? null : prev))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('workspace.deleteFailed'))
    } finally {
      setBusyId(null)
    }
  }, [t])

  const downloadAll = useCallback(async () => {
    const done = itemsRef.current.filter(item => item.status === 'completed' && item.result)
    if (done.length === 0) return
    if (done.length === 1) {
      await download(done[0])
      return
    }
    setDownloadingAll(true)
    try {
      const response = await fetch('/api/files/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: done.map(item => item.result!.id) }),
      })
      if (!response.ok) throw new Error(t('workspace.batchDownloadFailed'))
      downloadBlob(await response.blob(), `transmute_batch_${new Date().toISOString().split('T')[0]}.zip`)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('workspace.batchDownloadFailed'))
    } finally {
      setDownloadingAll(false)
    }
  }, [download, t])

  const clearReady = useCallback(() => {
    setItems(prev => prev.filter(item => !isReady(item)))
    setIgnoredCount(0)
  }, [])

  const clearCompleted = useCallback(() => {
    setItems(prev => prev.filter(item => item.status !== 'completed'))
  }, [])

  // Keep the selection valid as rows come and go.
  useEffect(() => {
    if (selectedId && !items.some(item => item.file.id === selectedId)) {
      setSelectedId(items[0]?.file.id ?? null)
    }
  }, [items, selectedId])

  return {
    items,
    selected: items.find(item => item.file.id === selectedId) ?? null,
    selectedId,
    setSelectedId,
    defaults,
    caps,
    presets,
    uploading: uploadCount > 0,
    uploadCount,
    ignoredCount,
    error,
    setError,
    submitting,
    downloadingAll,
    busyId,
    uploadFiles,
    uploadUrl,
    setOutput,
    patchItem,
    applyToAll,
    savePreset,
    submit,
    cancel,
    remove,
    download,
    downloadAll,
    clearReady,
    clearCompleted,
  }
}

export type WorkspaceState = ReturnType<typeof useWorkspace>
