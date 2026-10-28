import { lazy, Suspense, useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { FaArrowUpFromBracket, FaLink, FaXmark } from 'react-icons/fa6'
import { useTranslation } from 'react-i18next'
import Inspector from './Inspector'
import QueueList, { type PreviewTarget } from './QueueList'
import { isReady } from './model'
import { useWorkspace, type WorkspaceState } from './useWorkspace'

const PreviewModal = lazy(() => import('../../components/PreviewModal'))

function isMacPlatform() {
  if (typeof navigator === 'undefined') return false
  const platform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform
    || navigator.platform
    || navigator.userAgent
  return /mac|iphone|ipad|ipod/i.test(platform)
}

function DropZone({ state, inputRef, large }: { state: WorkspaceState; inputRef: RefObject<HTMLInputElement | null>; large: boolean }) {
  const { t } = useTranslation()
  const [dragOver, setDragOver] = useState(false)
  const openKey = isMacPlatform() ? '⌘O' : 'Ctrl+O'

  return (
    <label
      onDrop={event => {
        event.preventDefault()
        setDragOver(false)
        void state.uploadFiles(Array.from(event.dataTransfer.files))
      }}
      onDragOver={event => {
        event.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      className={`flex w-full cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-text-muted transition ${
        large ? 'h-44' : 'h-20'
      } ${dragOver ? 'border-primary bg-primary/10 text-text' : 'border-text/20 hover:border-primary/60 hover:bg-primary/5'}`}
    >
      <FaArrowUpFromBracket className={large ? 'mb-1 text-xl' : 'text-sm'} />
      <span className="text-sm">
        {state.uploading ? t('workspace.uploading', { count: state.uploadCount }) : t('workspace.dropFiles')}
      </span>
      <span className="font-mono text-[11px] text-text-muted/70">{t('workspace.dropHint', { key: openKey })}</span>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={event => {
          const files = event.target.files
          if (!files || files.length === 0) return
          void state.uploadFiles(Array.from(files))
          event.target.value = ''
        }}
      />
    </label>
  )
}

function UrlInput({ state }: { state: WorkspaceState }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState('')
  const valid = /^https?:\/\/.+/i.test(url.trim())
  const submit = async () => {
    if (!valid) return
    if (await state.uploadUrl(url)) setUrl('')
  }
  return (
    <div className="flex gap-2">
      <div className="relative min-w-0 flex-1">
        <FaLink className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[11px] text-text-muted" />
        <input
          type="url"
          inputMode="url"
          value={url}
          onChange={event => setUrl(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') void submit() }}
          placeholder={t('workspace.urlPlaceholder')}
          aria-label={t('workspace.urlPlaceholder')}
          className="field-control pl-7"
        />
      </div>
      <button type="button" className="btn" disabled={!valid} onClick={() => void submit()}>
        {t('workspace.addUrl')}
      </button>
    </div>
  )
}

function Notices({ state }: { state: WorkspaceState }) {
  const { t } = useTranslation()
  return (
    <>
      {state.error && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-xs text-accent">
          <span className="flex-1">{state.error}</span>
          <button type="button" aria-label={t('workspace.dismiss')} onClick={() => state.setError(null)}>
            <FaXmark />
          </button>
        </div>
      )}
      {state.ignoredCount > 0 && (
        <p className="rounded-md border border-text/10 px-3 py-2 text-xs text-text-muted">
          {t('workspace.ignored', { count: state.ignoredCount })}
        </p>
      )}
    </>
  )
}

function HardwareLine({ state }: { state: WorkspaceState }) {
  const { t } = useTranslation()
  const hw = state.caps?.hardware
  if (!state.caps) return null
  return (
    <p className="font-mono text-[11px] text-text-muted">
      {hw && hw.encoders.length > 0
        ? t('workspace.gpuReady', { encoders: hw.encoders.join(', ') })
        : t('workspace.cpuOnly')}
    </p>
  )
}

function Workspace() {
  const { t } = useTranslation()
  const state = useWorkspace()
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<PreviewTarget | null>(null)
  const stateRef = useRef(state)
  useEffect(() => { stateRef.current = state })

  const onKeyDown = useCallback((event: KeyboardEvent) => {
    const mod = event.ctrlKey || event.metaKey
    const key = event.key.toUpperCase()
    if (mod && key === 'O') {
      event.preventDefault()
      inputRef.current?.click()
    } else if (mod && key === 'ENTER') {
      event.preventDefault()
      void stateRef.current.submit()
    } else if (key === 'ESCAPE' && !preview) {
      stateRef.current.clearReady()
    }
  }, [preview])

  useEffect(() => {
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onKeyDown])

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const clipboard = event.clipboardData
      if (!clipboard) return
      const keyOf = (f: File) => `${f.name}|${f.size}|${f.type}|${f.lastModified}`
      const direct = Array.from(clipboard.files ?? [])
      const seen = new Set(direct.map(keyOf))
      const fromItems: File[] = []
      for (const item of Array.from(clipboard.items ?? [])) {
        if (item.kind !== 'file') continue
        const file = item.getAsFile()
        if (!file || seen.has(keyOf(file))) continue
        seen.add(keyOf(file))
        fromItems.push(file)
      }
      const files = [...direct, ...fromItems]
      if (files.length > 0) {
        event.preventDefault()
        void stateRef.current.uploadFiles(files)
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [])

  const empty = state.items.length === 0 && !state.uploading
  const readyCount = state.items.filter(isReady).length

  return (
    <div className="h-full bg-surface-dark">
      {empty ? (
        <div className="flex h-full items-center justify-center p-4">
          <div className="w-full max-w-xl space-y-4">
            <div className="space-y-1 text-center">
              <h1 className="text-xl font-medium text-text">{t('workspace.landingTitle')}</h1>
              <p className="text-sm text-text-muted">{t('workspace.landingSubtitle')}</p>
            </div>
            <DropZone state={state} inputRef={inputRef} large />
            <UrlInput state={state} />
            <Notices state={state} />
            <div className="text-center"><HardwareLine state={state} /></div>
          </div>
        </div>
      ) : (
        <div className="mx-auto grid h-full max-w-7xl grid-cols-1 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
          <aside className="flex min-h-0 flex-col border-text/10 bg-surface-dark lg:border-r">
            <div className="space-y-2 p-3">
              <DropZone state={state} inputRef={inputRef} large={false} />
              <UrlInput state={state} />
              <Notices state={state} />
            </div>
            <QueueList state={state} onPreview={setPreview} />
            <div className="mt-auto border-t border-text/10 px-3 py-2">
              <HardwareLine state={state} />
              {readyCount > 0 && (
                <p className="font-mono text-[11px] text-text-muted/70">
                  {t('workspace.hotkeys', { submit: isMacPlatform() ? '⌘↵' : 'Ctrl+Enter' })}
                </p>
              )}
            </div>
          </aside>
          <section className="min-h-0 overflow-auto bg-surface-dark">
            {state.selected ? (
              <Inspector key={state.selected.file.id} state={state} item={state.selected} />
            ) : (
              <p className="p-6 text-sm text-text-muted">{t('workspace.selectFile')}</p>
            )}
          </section>
        </div>
      )}

      {preview && (
        <Suspense fallback={null}>
          <PreviewModal
            fileId={preview.id}
            filename={preview.filename}
            mediaType={preview.mediaType}
            onClose={() => setPreview(null)}
          />
        </Suspense>
      )}
    </div>
  )
}

export default Workspace
