/*
  encoding.ts
  -----------
  Types and API calls for the advanced encoding endpoints:
  GET /api/capabilities, /api/presets, GET /api/files/{id}/probe, and the
  request bodies the workspace sends to the job endpoints.
*/
import { apiJson } from './api'

export type VideoCodec = 'h264' | 'hevc' | 'av1' | 'vp9' | 'copy'
export type RateControl = 'crf' | 'cqp' | 'vbr' | 'cbr' | 'target_size'
export type AudioCodec = 'aac' | 'opus' | 'mp3' | 'flac' | 'ac3' | 'vorbis' | 'pcm' | 'copy' | 'none'
export type ChromaSubsampling = '4:2:0' | '4:2:2' | '4:4:4'

export interface VideoOptions {
  codec?: VideoCodec
  encoder?: string
  rate_control?: RateControl
  crf?: number
  qp?: number
  bitrate_kbps?: number
  maxrate_kbps?: number
  target_size_mb?: number
  encoder_preset?: string | number
  tune?: string
  bit_depth?: 8 | 10
  max_width?: number
  max_height?: number
  fps?: number
  keyframe_interval_s?: number
}

export interface AudioOptions {
  codec?: AudioCodec
  bitrate_kbps?: number
  channels?: number
  sample_rate?: number
}

export interface ImageOptions {
  quality?: number
  lossless?: boolean
  effort?: number
  chroma_subsampling?: ChromaSubsampling
  max_dimension?: number
  palette_colors?: number
}

export interface EncodeOptions {
  video?: VideoOptions
  audio?: AudioOptions
  image?: ImageOptions
  trim?: { start_s?: number; end_s?: number }
  subtitles?: 'copy' | 'drop'
  strip_metadata?: boolean
  keep_if_larger?: boolean
  hw_fallback?: boolean
}

export interface VideoEncoderInfo {
  name: string
  codec: string
  hardware: string | null
  rate_controls: string[]
  quality_param: 'crf' | 'qp'
  quality_range: [number, number]
  default_quality: number
  presets: Array<string | number>
  default_preset: string | number | null
  tunes: string[]
  bit_depths: number[]
  two_pass: boolean
}

export interface ContainerInfo {
  format: string
  kind: 'video' | 'audio'
  video_codecs: string[]
  audio_codecs: string[]
  default_video: string | null
  default_audio: string | null
  subtitle_copy: boolean
}

export interface ImageFormatInfo {
  format: string
  quality: boolean
  lossless: boolean
  effort: boolean
  chroma_subsampling: boolean
  palette_colors: boolean
}

export interface Preset {
  id: string
  name: string
  description?: string | null
  kind: 'video' | 'image'
  builtin: boolean
  options: EncodeOptions
  created_at?: string | null
  updated_at?: string | null
}

export interface Capabilities {
  ffmpeg_version: string | null
  hardware: {
    vaapi_device: string | null
    driver: string | null
    encoders: string[]
    ten_bit_encoders: string[]
  }
  video_encoders: VideoEncoderInfo[]
  default_video_encoders: Record<string, string | null>
  audio_codecs: string[]
  containers: ContainerInfo[]
  image_formats: ImageFormatInfo[]
  presets: Preset[]
}

export interface ProbeResult {
  id: string
  media_type: string
  kind: 'video' | 'audio' | 'image' | 'other'
  duration_s?: number | null
  bitrate_kbps?: number | null
  container?: string | null
  video?: {
    codec?: string | null
    width?: number | null
    height?: number | null
    fps?: number | null
    pix_fmt?: string | null
    bit_depth?: number | null
  } | null
  audio?: Array<{ codec?: string | null; channels?: number | null; sample_rate?: number | null; bitrate_kbps?: number | null }>
  subtitle_count?: number
  image?: {
    width: number
    height: number
    mode: string
    format?: string | null
    frames: number
    has_exif: boolean
    has_icc: boolean
  } | null
}

export interface PresetDraft {
  name: string
  description?: string | null
  kind: 'video' | 'image'
  options: EncodeOptions
}

let capabilitiesPromise: Promise<Capabilities> | null = null

/** Capabilities rarely change while the app runs, so fetch them once. */
export function getCapabilities(force = false): Promise<Capabilities> {
  if (!capabilitiesPromise || force) {
    capabilitiesPromise = apiJson<Capabilities>('/api/capabilities').catch((err) => {
      capabilitiesPromise = null
      throw err
    })
  }
  return capabilitiesPromise
}

export async function listPresets(): Promise<Preset[]> {
  const data = await apiJson<{ presets: Preset[] }>('/api/presets')
  return data.presets
}

export function createPreset(draft: PresetDraft): Promise<Preset> {
  return apiJson<Preset>('/api/presets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(draft),
  })
}

export function updatePreset(id: string, patch: Partial<PresetDraft>): Promise<Preset> {
  return apiJson<Preset>(`/api/presets/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export async function deletePreset(id: string): Promise<void> {
  await apiJson<void>(`/api/presets/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function probeFile(fileId: string): Promise<ProbeResult> {
  return apiJson<ProbeResult>(`/api/files/${encodeURIComponent(fileId)}/probe`)
}

/** Drop undefined values and empty sections so requests only carry what the user set. */
export function pruneOptions(options: EncodeOptions): EncodeOptions | undefined {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(options)) {
    if (value === undefined || value === null || value === '') continue
    if (typeof value === 'object' && !Array.isArray(value)) {
      const section = Object.fromEntries(
        Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== undefined && v !== null && v !== ''),
      )
      if (Object.keys(section).length > 0) out[key] = section
      continue
    }
    out[key] = value
  }
  return Object.keys(out).length > 0 ? (out as EncodeOptions) : undefined
}

export function containerFor(caps: Capabilities | null, format: string): ContainerInfo | undefined {
  return caps?.containers.find(c => c.format === format)
}

export function imageFormatFor(caps: Capabilities | null, format: string): ImageFormatInfo | undefined {
  return caps?.image_formats.find(f => f.format === format)
}

export function encoderInfo(caps: Capabilities | null, name: string | undefined | null): VideoEncoderInfo | undefined {
  return name ? caps?.video_encoders.find(e => e.name === name) : undefined
}

/** Human-friendly byte size (binary units, as the rest of the app shows). */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = String(m).padStart(h > 0 ? 2 : 1, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}
