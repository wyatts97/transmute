/*
  Workspace data model and the pure helpers that turn a queue row into the
  exact API request it will send.
*/
import type { ConversionInfo, FileInfo } from '../../components/FileTable'
import { api } from '../../utils/api'
import {
  containerFor,
  encoderInfo,
  imageFormatFor,
  pruneOptions,
  type Capabilities,
  type ContainerInfo,
  type EncodeOptions,
  type ImageFormatInfo,
  type Preset,
  type ProbeResult,
  type VideoEncoderInfo,
} from '../../utils/encoding'

export type ItemStatus = 'ready' | 'queued' | 'running' | 'failed' | 'cancelled' | 'completed'
export type JobKind = 'convert' | 'compress'

export interface ItemJob {
  id: string
  kind: JobKind
  progress: number | null
  etaSeconds: number | null
  speed: number | null
  /** Running jobs can only be stopped when submitted with options/preset. */
  cancellable: boolean
}

export interface ItemResult extends ConversionInfo {
  encoder_used?: string | null
}

export interface WorkspaceItem {
  file: FileInfo
  /** '' keeps the source format (compression); anything else converts. */
  output: string
  quality?: string
  compressionLevel?: string
  preset?: string
  /** Only the fields the user set; everything else is inherited. */
  options: EncodeOptions
  status: ItemStatus
  error?: string
  job?: ItemJob
  result?: ItemResult
  /** undefined = not loaded yet, null = probe failed or not applicable. */
  probe?: ProbeResult | null
}

export interface WorkspaceDefaults {
  defaultFormats: Record<string, string>
  aliases: Record<string, string>
  defaultQualities: Record<string, string>
  defaultCompressionLevels: Record<string, string>
  compressionLevelsByFormat: Record<string, string[]>
  compressibleFormats: Set<string>
}

export const EMPTY_DEFAULTS: WorkspaceDefaults = {
  defaultFormats: {},
  aliases: {},
  defaultQualities: {},
  defaultCompressionLevels: {},
  compressionLevelsByFormat: {},
  compressibleFormats: new Set(),
}

const COMPRESSION_LEVEL_ORDER: Record<string, number> = { light: 0, balanced: 1, max: 2 }
const QUALITY_ORDER: Record<string, number> = { low: 0, medium: 1, high: 2 }

export function sortCompressionLevels(levels: string[]): string[] {
  return [...levels].sort((a, b) => (COMPRESSION_LEVEL_ORDER[a] ?? 99) - (COMPRESSION_LEVEL_ORDER[b] ?? 99))
}

export function sortQualities(qualities: string[]): string[] {
  return [...qualities].sort((a, b) => (QUALITY_ORDER[a] ?? 99) - (QUALITY_ORDER[b] ?? 99))
}

export function normalizeFormat(format: string, defaults: WorkspaceDefaults): string {
  const lower = format.replace(/^\./, '').toLowerCase()
  return defaults.aliases[lower] || lower
}

export function isCompressible(file: FileInfo, defaults: WorkspaceDefaults): boolean {
  return defaults.compressibleFormats.has(file.media_type)
    || defaults.compressibleFormats.has(normalizeFormat(file.media_type, defaults))
}

export function compressionLevelsFor(file: FileInfo, defaults: WorkspaceDefaults): string[] {
  return defaults.compressionLevelsByFormat[file.media_type]
    || defaults.compressionLevelsByFormat[normalizeFormat(file.media_type, defaults)]
    || []
}

export function convertFormats(file: FileInfo): string[] {
  return file.compatible_formats ? Object.keys(file.compatible_formats).sort() : []
}

export function qualitiesFor(file: FileInfo, output: string): string[] {
  return output ? sortQualities(file.compatible_formats?.[output] || []) : []
}

/** Whether a file can be acted on at all (converted or compressed). */
export function isActionable(file: FileInfo, defaults: WorkspaceDefaults): boolean {
  return isCompressible(file, defaults) || convertFormats(file).length > 0
}

export function defaultQualityFor(file: FileInfo, output: string, defaults: WorkspaceDefaults): string | undefined {
  const qualities = qualitiesFor(file, output)
  if (qualities.length === 0) return undefined
  const preferred = defaults.defaultQualities[output]
  if (preferred && qualities.includes(preferred)) return preferred
  return qualities.includes('medium') ? 'medium' : undefined
}

export function defaultLevelFor(file: FileInfo, defaults: WorkspaceDefaults): string | undefined {
  const levels = compressionLevelsFor(file, defaults)
  if (levels.length === 0) return undefined
  const preferred = defaults.defaultCompressionLevels[file.media_type]
    ?? defaults.defaultCompressionLevels[normalizeFormat(file.media_type, defaults)]
  if (preferred && levels.includes(preferred)) return preferred
  return levels.includes('balanced') ? 'balanced' : sortCompressionLevels(levels)[0]
}

/**
 * Pick a starting output for a new upload: the user's default conversion for
 * this input, otherwise "same format" compression when available, otherwise
 * the first compatible format.
 */
export function initialOutput(file: FileInfo, defaults: WorkspaceDefaults): string {
  const formats = convertFormats(file)
  const input = normalizeFormat(file.extension || file.media_type, defaults)
  const preferred = defaults.defaultFormats[input] || defaults.defaultFormats[file.media_type]
  if (preferred && formats.includes(preferred)) return preferred
  if (isCompressible(file, defaults)) return ''
  return formats[0] || ''
}

export function makeItem(file: FileInfo, defaults: WorkspaceDefaults): WorkspaceItem {
  const output = initialOutput(file, defaults)
  return withOutput({ file, output: '', options: {}, status: 'ready' }, output, defaults)
}

/** Switch output and reset settings that only make sense for the old target. */
export function withOutput(item: WorkspaceItem, output: string, defaults: WorkspaceDefaults): WorkspaceItem {
  const sameKind = targetKey(item, defaults) === targetKey({ ...item, output }, defaults)
  return {
    ...item,
    output,
    quality: output ? defaultQualityFor(item.file, output, defaults) : undefined,
    compressionLevel: output ? undefined : defaultLevelFor(item.file, defaults),
    options: sameKind ? item.options : {},
    preset: sameKind ? item.preset : undefined,
    status: item.status === 'failed' || item.status === 'cancelled' ? 'ready' : item.status,
    error: undefined,
  }
}

/** The format the encoder writes: the source format when compressing. */
export function targetFormat(item: WorkspaceItem, defaults: WorkspaceDefaults): string {
  return item.output || normalizeFormat(item.file.media_type, defaults)
}

export type PanelKind = 'video' | 'audio' | 'image' | 'none'

export interface TargetInfo {
  format: string
  panel: PanelKind
  container?: ContainerInfo
  image?: ImageFormatInfo
}

export function targetInfo(item: WorkspaceItem, defaults: WorkspaceDefaults, caps: Capabilities | null): TargetInfo {
  const format = targetFormat(item, defaults)
  const container = containerFor(caps, format)
  if (container) return { format, panel: container.kind, container }
  const image = imageFormatFor(caps, format)
  if (image) return { format, panel: 'image', image }
  return { format, panel: 'none' }
}

function targetKey(item: WorkspaceItem, defaults: WorkspaceDefaults): string {
  return targetFormat(item, defaults)
}

export function presetsFor(panel: PanelKind, presets: Preset[]): Preset[] {
  if (panel === 'video') return presets.filter(p => p.kind === 'video')
  if (panel === 'image') return presets.filter(p => p.kind === 'image')
  return []
}

export interface JobRequest {
  kind: JobKind
  endpoint: '/api/jobs' | '/api/compression-jobs'
  body: Record<string, unknown>
}

export function buildRequest(item: WorkspaceItem): JobRequest {
  const options = pruneOptions(item.options)
  const extras: Record<string, unknown> = {}
  if (item.preset) extras.preset = item.preset
  if (options) extras.options = options
  if (!item.output) {
    return {
      kind: 'compress',
      endpoint: '/api/compression-jobs',
      body: {
        id: item.file.id,
        ...(item.compressionLevel ? { compression_level: item.compressionLevel } : {}),
        ...extras,
      },
    }
  }
  return {
    kind: 'convert',
    endpoint: '/api/jobs',
    body: {
      id: item.file.id,
      output_format: item.output,
      ...(item.quality ? { quality: item.quality } : {}),
      ...extras,
    },
  }
}

/** The request as a copy-pasteable curl command (API key left as an env var). */
export function curlCommand(request: JobRequest): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const body = JSON.stringify(request.body).replace(/'/g, "'\\''")
  return [
    `curl -X POST "${origin}${api.url(request.endpoint)}"`,
    '  -H "Authorization: Bearer $TRANSMUTE_API_KEY"',
    '  -H "Content-Type: application/json"',
    `  -d '${body}'`,
  ].join(' \\\n')
}

export function usesAdvancedPath(item: WorkspaceItem): boolean {
  return !!item.preset || !!pruneOptions(item.options)
}

export function isReady(item: WorkspaceItem): boolean {
  return item.status === 'ready' || item.status === 'failed' || item.status === 'cancelled'
}

export function isActive(item: WorkspaceItem): boolean {
  return item.status === 'queued' || item.status === 'running'
}

/** Effective video settings for display: user fields over the preset's. */
export function effectiveVideo(item: WorkspaceItem, presets: Preset[], container: ContainerInfo | undefined, caps: Capabilities | null) {
  const preset = presets.find(p => p.id === item.preset)
  const inherited = preset?.options.video ?? {}
  const own = item.options.video ?? {}
  const codec = own.codec ?? inherited.codec ?? container?.default_video ?? undefined
  const bitDepth = own.bit_depth ?? inherited.bit_depth ?? 8
  let encoderName = own.encoder ?? (own.codec ? undefined : inherited.encoder)
  if (!encoderName && codec && codec !== 'copy') {
    const preferred = caps?.default_video_encoders[codec] ?? undefined
    const preferredInfo = encoderInfo(caps, preferred)
    // A GPU that failed the 10-bit test can't take a 10-bit encode.
    if (preferredInfo?.hardware && bitDepth === 10 && !caps?.hardware.ten_bit_encoders.includes(preferredInfo.name)) {
      encoderName = caps?.video_encoders.find(e => e.codec === codec && !e.hardware && e.bit_depths.includes(10))?.name
    } else {
      encoderName = preferred ?? undefined
    }
  }
  const encoder: VideoEncoderInfo | undefined = encoderInfo(caps, encoderName)
  return { codec, encoder, inherited, bitDepth }
}

export function encodersForCodec(caps: Capabilities | null, codec: string | undefined): VideoEncoderInfo[] {
  if (!caps || !codec) return []
  return caps.video_encoders
    .filter(e => e.codec === codec)
    .sort((a, b) => Number(!!b.hardware) - Number(!!a.hardware))
}
