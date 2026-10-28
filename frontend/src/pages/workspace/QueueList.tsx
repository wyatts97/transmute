import type { ReactNode } from 'react'
import { FaDownload, FaEye, FaStop, FaTrashCan } from 'react-icons/fa6'
import { useTranslation } from 'react-i18next'
import { isPreviewable } from '../../components/previewUtils'
import { ProgressBar } from '../../ui/controls'
import { formatBytes, formatDuration } from '../../utils/encoding'
import { isActive, isReady, normalizeFormat, type WorkspaceItem } from './model'
import type { WorkspaceState } from './useWorkspace'

export interface PreviewTarget {
  id: string
  filename: string
  mediaType: string
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={event => {
        event.stopPropagation()
        onClick()
      }}
      className="rounded p-1.5 text-text-muted transition hover:bg-text/10 hover:text-text disabled:opacity-40"
    >
      {children}
    </button>
  )
}

function Row({ item, state, selected, onPreview }: {
  item: WorkspaceItem
  state: WorkspaceState
  selected: boolean
  onPreview: (target: PreviewTarget) => void
}) {
  const { t } = useTranslation()
  const source = normalizeFormat(item.file.media_type, state.defaults)
  const target = item.output || source
  const presetName = state.presets.find(p => p.id === item.preset)?.name
  const busy = state.busyId === item.file.id
  const result = item.result
  const previewable = result ? isPreviewable(result.media_type) : isPreviewable(item.file.media_type)
  const canCancel = item.status === 'queued' || (item.status === 'running' && !!item.job?.cancellable)

  return (
    <li
      className={`group cursor-pointer border-b border-text/10 px-3 py-2.5 transition ${selected ? 'bg-surface-light shadow-[inset_2px_0_0_rgb(var(--color-primary))]' : 'hover:bg-text/[0.03]'}`}
      onClick={() => state.setSelectedId(item.file.id)}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-sm text-text">{item.file.original_filename}</span>
            <span className="shrink-0 font-mono text-[11px] text-text-muted">{formatBytes(item.file.size_bytes)}</span>
          </div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-text-muted">
            {item.output ? `${source} → ${target}` : t('workspace.compressShort', { format: source })}
            {presetName ? ` · ${presetName}` : ''}
            {' · '}
            <span className={item.status === 'failed' ? 'text-accent' : item.status === 'completed' ? 'text-primary' : ''}>
              {t(`workspace.status.${item.status}`)}
            </span>
          </div>
        </div>
        <div className={`flex shrink-0 items-center ${selected ? '' : 'opacity-70 group-hover:opacity-100'}`}>
          {previewable && (
            <IconButton
              label={t('workspace.preview')}
              onClick={() => onPreview(result
                ? { id: result.id, filename: result.original_filename, mediaType: result.media_type }
                : { id: item.file.id, filename: item.file.original_filename, mediaType: item.file.media_type })}
            >
              <FaEye className="text-xs" />
            </IconButton>
          )}
          {item.status === 'completed' && (
            <IconButton label={t('workspace.download')} onClick={() => state.download(item)} disabled={busy}>
              <FaDownload className="text-xs" />
            </IconButton>
          )}
          {canCancel && (
            <IconButton label={t('workspace.cancelJob')} onClick={() => state.cancel(item.file.id)} disabled={busy}>
              <FaStop className="text-xs" />
            </IconButton>
          )}
          {(isReady(item) || item.status === 'completed') && (
            <IconButton label={t('workspace.remove')} onClick={() => state.remove(item.file.id)} disabled={busy}>
              <FaTrashCan className="text-xs" />
            </IconButton>
          )}
        </div>
      </div>

      {isActive(item) && (
        <div className="mt-2 space-y-1">
          <ProgressBar percent={item.status === 'running' ? item.job?.progress ?? null : 0} tone={item.status === 'running' ? 'primary' : 'muted'} />
          {item.status === 'running' && (
            <div className="font-mono text-[11px] text-primary">
              {item.job?.progress != null ? `${item.job.progress}%` : t('workspace.status.running')}
              {item.job?.speed ? ` · ${item.job.speed.toFixed(1)}×` : ''}
              {item.job?.etaSeconds ? ` · ${t('workspace.eta', { time: formatDuration(item.job.etaSeconds) })}` : ''}
            </div>
          )}
        </div>
      )}
      {item.status === 'completed' && result && result.size_bytes > 0 && (
        <div className="mt-1 font-mono text-[11px] text-text-muted">
          → {formatBytes(result.size_bytes)}
          <span className={result.size_bytes <= item.file.size_bytes ? 'ml-1.5 text-primary' : 'ml-1.5 text-accent'}>
            {result.size_bytes <= item.file.size_bytes ? '−' : '+'}{Math.abs(Math.round((1 - result.size_bytes / item.file.size_bytes) * 100))}%
          </span>
          {result.encoder_used && <span className="ml-1.5">{result.encoder_used}</span>}
        </div>
      )}
      {item.status === 'failed' && item.error && (
        <p className="mt-1 line-clamp-2 text-[11px] text-accent">{item.error}</p>
      )}
    </li>
  )
}

export default function QueueList({ state, onPreview }: { state: WorkspaceState; onPreview: (target: PreviewTarget) => void }) {
  const { t } = useTranslation()
  const readyCount = state.items.filter(isReady).length
  const activeCount = state.items.filter(isActive).length
  const doneCount = state.items.filter(item => item.status === 'completed').length

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-text/10 px-3 py-2">
        <span className="font-mono text-[11px] text-text-muted">
          {t('workspace.queueSummary', { total: state.items.length, active: activeCount, done: doneCount })}
        </span>
        <div className="flex gap-1.5">
          {doneCount > 1 && (
            <button type="button" className="btn h-7 px-2 text-[11px]" onClick={() => state.downloadAll()} disabled={state.downloadingAll}>
              <FaDownload /> {t('workspace.downloadAll', { count: doneCount })}
            </button>
          )}
          {doneCount > 0 && (
            <button type="button" className="btn h-7 px-2 text-[11px]" onClick={state.clearCompleted}>
              {t('workspace.clearDone')}
            </button>
          )}
          <button
            type="button"
            className="btn-primary h-7 px-2 text-[11px]"
            onClick={() => state.submit()}
            disabled={state.submitting || readyCount === 0}
          >
            {t('workspace.queueAll', { count: readyCount })}
          </button>
        </div>
      </div>
      <ul className="min-h-0 flex-1 overflow-auto">
        {state.items.map(item => (
          <Row key={item.file.id} item={item} state={state} selected={item.file.id === state.selectedId} onPreview={onPreview} />
        ))}
      </ul>
    </div>
  )
}
