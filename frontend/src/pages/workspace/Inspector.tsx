import { useState } from 'react'
import { FaCopy, FaDownload, FaFloppyDisk, FaPlay } from 'react-icons/fa6'
import { useTranslation } from 'react-i18next'
import { Field, ProgressBar } from '../../ui/controls'
import { formatBytes, formatDuration, pruneOptions, type ProbeResult } from '../../utils/encoding'
import ApiPreview from './ApiPreview'
import ImagePanel from './ImagePanel'
import VideoPanel from './VideoPanel'
import {
  buildRequest,
  compressionLevelsFor,
  convertFormats,
  isCompressible,
  isReady,
  normalizeFormat,
  presetsFor,
  qualitiesFor,
  targetInfo,
  type WorkspaceItem,
} from './model'
import type { WorkspaceState } from './useWorkspace'

function probeSummary(probe: ProbeResult): string[] {
  const parts: string[] = []
  if (probe.image) {
    parts.push(`${probe.image.width}×${probe.image.height}`, probe.image.mode)
    if (probe.image.frames > 1) parts.push(`${probe.image.frames} frames`)
    if (probe.image.has_exif) parts.push('EXIF')
    if (probe.image.has_icc) parts.push('ICC')
    return parts
  }
  const video = probe.video
  if (video?.width && video.height) parts.push(`${video.width}×${video.height}`)
  if (video?.fps) parts.push(`${Math.round(video.fps * 1000) / 1000} fps`)
  if (video?.codec) parts.push(video.codec + (video.bit_depth && video.bit_depth > 8 ? ` ${video.bit_depth}-bit` : ''))
  if (probe.bitrate_kbps) parts.push(probe.bitrate_kbps >= 1000 ? `${(probe.bitrate_kbps / 1000).toFixed(1)} Mb/s` : `${probe.bitrate_kbps} kb/s`)
  if (probe.duration_s) parts.push(formatDuration(probe.duration_s))
  const audio = probe.audio?.[0]
  if (audio?.codec) parts.push(`${audio.codec}${audio.channels ? ` ${audio.channels}ch` : ''}`)
  return parts
}

/** Output size we can predict without encoding: only for size/bitrate targets. */
function predictedBytes(item: WorkspaceItem): number | null {
  const video = item.options.video
  if (video?.rate_control === 'target_size' && video.target_size_mb) return video.target_size_mb * 1024 * 1024
  const duration = item.probe?.duration_s
  if (duration && video?.bitrate_kbps && (video.rate_control === 'vbr' || video.rate_control === 'cbr')) {
    const audioKbps = item.options.audio?.bitrate_kbps ?? 128
    return ((video.bitrate_kbps + audioKbps) * 1000 / 8) * duration
  }
  return null
}

export default function Inspector({ state, item }: { state: WorkspaceState; item: WorkspaceItem }) {
  const { t } = useTranslation()
  const [presetName, setPresetName] = useState<string | null>(null)
  const { defaults, caps, presets } = state
  const ready = isReady(item)
  const compress = !item.output
  const target = targetInfo(item, defaults, caps)
  const formats = convertFormats(item.file)
  const canCompress = isCompressible(item.file, defaults)
  const basePresets = compress ? compressionLevelsFor(item.file, defaults) : qualitiesFor(item.file, item.output)
  const availablePresets = presetsFor(target.panel, presets)
  const request = buildRequest(item)
  const predicted = predictedBytes(item)
  const readyCount = state.items.filter(isReady).length
  const sourceFormat = normalizeFormat(item.file.media_type, defaults)
  const hasCustomSettings = !!item.preset || !!pruneOptions(item.options)

  return (
    <div className="space-y-5 p-4 sm:p-5">
      <header className="space-y-1">
        <div className="flex items-baseline gap-3">
          <h2 className="truncate text-base font-medium text-text" title={item.file.original_filename}>{item.file.original_filename}</h2>
          <span className="shrink-0 font-mono text-[11px] text-text-muted">{formatBytes(item.file.size_bytes)}</span>
        </div>
        <p className="min-h-4 font-mono text-[11px] text-text-muted">
          {item.probe === undefined && t('workspace.readingMedia')}
          {item.probe && probeSummary(item.probe).join(' · ')}
        </p>
      </header>

      {item.status === 'running' || item.status === 'queued' ? (
        <div className="panel space-y-2 p-3">
          <div className="flex justify-between font-mono text-xs">
            <span>{t(`workspace.status.${item.status}`)}</span>
            <span className="text-text-muted">
              {item.job?.progress != null && `${item.job.progress}%`}
              {item.job?.speed ? ` · ${item.job.speed.toFixed(1)}×` : ''}
              {item.job?.etaSeconds ? ` · ${t('workspace.eta', { time: formatDuration(item.job.etaSeconds) })}` : ''}
            </span>
          </div>
          <ProgressBar percent={item.status === 'running' ? item.job?.progress ?? null : 0} />
        </div>
      ) : null}

      {item.status === 'completed' && item.result && (
        <div className="panel flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="font-mono text-xs">
            <span>{formatBytes(item.result.size_bytes)}</span>
            {item.result.size_bytes > 0 && (
              <span className={item.result.size_bytes <= item.file.size_bytes ? 'ml-2 text-primary' : 'ml-2 text-accent'}>
                {item.result.size_bytes <= item.file.size_bytes ? '−' : '+'}
                {Math.abs(Math.round((1 - item.result.size_bytes / item.file.size_bytes) * 100))}%
              </span>
            )}
            {item.result.encoder_used && <span className="ml-2 text-text-muted">{item.result.encoder_used}</span>}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn" onClick={() => state.download(item)} disabled={state.busyId === item.file.id}>
              <FaDownload /> {t('workspace.download')}
            </button>
          </div>
        </div>
      )}

      {item.error && (item.status === 'failed' || item.status === 'ready') && (
        <p role="alert" className="rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-xs text-accent">{item.error}</p>
      )}

      <fieldset disabled={!ready} className="space-y-5 disabled:opacity-60">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={t('workspace.output')}>
            <select className="field-control" value={item.output} onChange={event => state.setOutput(item.file.id, event.target.value)}>
              {canCompress && <option value="">{t('workspace.sameFormat', { format: sourceFormat })}</option>}
              {formats.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          </Field>
          <Field label={t('workspace.preset')}>
            <select
              className="field-control"
              value={item.preset ?? ''}
              disabled={availablePresets.length === 0}
              onChange={event => state.patchItem(item.file.id, { preset: event.target.value || undefined })}
            >
              <option value="">{t('workspace.noPreset')}</option>
              {availablePresets.some(p => p.builtin) && (
                <optgroup label={t('workspace.builtinPresets')}>
                  {availablePresets.filter(p => p.builtin).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </optgroup>
              )}
              {availablePresets.some(p => !p.builtin) && (
                <optgroup label={t('workspace.savedPresets')}>
                  {availablePresets.filter(p => !p.builtin).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </optgroup>
              )}
            </select>
          </Field>
          {basePresets.length > 0 && (
            <Field label={compress ? t('workspace.compressionLevel') : t('workspace.baseQuality')}>
              <select
                className="field-control"
                value={(compress ? item.compressionLevel : item.quality) ?? ''}
                onChange={event => state.patchItem(item.file.id, compress
                  ? { compressionLevel: event.target.value || undefined }
                  : { quality: event.target.value || undefined })}
              >
                {!compress && <option value="">{t('workspace.default')}</option>}
                {basePresets.map(level => (
                  <option key={level} value={level}>
                    {compress ? t(`workspace.levels.${level}`, { defaultValue: level }) : t(`workspace.qualities.${level}`, { defaultValue: level })}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
        {item.preset && (
          <p className="text-[11px] text-text-muted">
            {availablePresets.find(p => p.id === item.preset)?.description || t('workspace.presetApplied')}
          </p>
        )}

        {(target.panel === 'video' || target.panel === 'audio') && target.container && (
          <VideoPanel
            item={item}
            container={target.container}
            caps={caps}
            presets={presets}
            probe={item.probe}
            compress={compress}
            onChange={options => state.patchItem(item.file.id, { options })}
          />
        )}
        {target.panel === 'image' && target.image && (
          <ImagePanel
            item={item}
            format={target.image}
            presets={presets}
            probe={item.probe}
            compress={compress}
            onChange={options => state.patchItem(item.file.id, { options })}
          />
        )}
        {target.panel === 'none' && (
          <p className="text-xs text-text-muted">{t('workspace.noAdvanced', { format: target.format })}</p>
        )}
      </fieldset>

      {predicted !== null && (
        <div className="panel space-y-2 p-3">
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">{t('workspace.estimatedOutput')}</span>
            <span className="font-mono">
              ≈ {formatBytes(predicted)}
              <span className={predicted <= item.file.size_bytes ? 'ml-2 text-primary' : 'ml-2 text-accent'}>
                {predicted <= item.file.size_bytes ? '−' : '+'}{Math.abs(Math.round((1 - predicted / item.file.size_bytes) * 100))}%
              </span>
            </span>
          </div>
          <ProgressBar percent={Math.min(100, (predicted / item.file.size_bytes) * 100)} />
        </div>
      )}

      {ready && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {presetName === null ? (
            target.panel !== 'none' && hasCustomSettings && (
              <button type="button" className="btn" onClick={() => setPresetName('')}>
                <FaFloppyDisk /> {t('workspace.saveAsPreset')}
              </button>
            )
          ) : (
            <form
              className="flex items-center gap-2"
              onSubmit={event => {
                event.preventDefault()
                if (!presetName.trim()) return
                void state.savePreset(item.file.id, presetName.trim())
                setPresetName(null)
              }}
            >
              <input
                autoFocus
                className="field-control w-44"
                value={presetName}
                onChange={event => setPresetName(event.target.value)}
                placeholder={t('workspace.presetNamePlaceholder')}
                aria-label={t('workspace.presetName')}
              />
              <button type="submit" className="btn" disabled={!presetName.trim()}>{t('workspace.save')}</button>
              <button type="button" className="btn" onClick={() => setPresetName(null)}>{t('workspace.cancel')}</button>
            </form>
          )}
          {readyCount > 1 && (
            <button type="button" className="btn" onClick={() => state.applyToAll(item.file.id)}>
              <FaCopy /> {t('workspace.applyToAll')}
            </button>
          )}
          <button type="button" className="btn-primary" onClick={() => state.submit([item.file.id])} disabled={state.submitting}>
            <FaPlay /> {t('workspace.queueJob')}
          </button>
        </div>
      )}

      <ApiPreview request={request} />
    </div>
  )
}
