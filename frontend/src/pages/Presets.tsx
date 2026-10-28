import { useEffect, useState } from 'react'
import { FaCopy, FaPenToSquare, FaPlus, FaTrashCan } from 'react-icons/fa6'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { createPreset, deletePreset, listPresets, updatePreset, type EncodeOptions, type Preset } from '../utils/encoding'

interface Draft {
  id?: string
  name: string
  description: string
  kind: 'video' | 'image'
  optionsText: string
}

const EMPTY_DRAFT: Draft = { name: '', description: '', kind: 'video', optionsText: '{\n  "video": {"codec": "hevc", "crf": 24}\n}' }

function PresetEditor({ draft, onChange, onSave, onCancel, saving, error }: {
  draft: Draft
  onChange: (draft: Draft) => void
  onSave: () => void
  onCancel: () => void
  saving: boolean
  error: string | null
}) {
  const { t } = useTranslation()
  return (
    <form
      className="panel space-y-3 p-4"
      onSubmit={event => {
        event.preventDefault()
        onSave()
      }}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_140px]">
        <label>
          <span className="field-label">{t('presets.name')}</span>
          <input className="field-control" value={draft.name} maxLength={64} onChange={event => onChange({ ...draft, name: event.target.value })} />
        </label>
        <label>
          <span className="field-label">{t('presets.kind')}</span>
          <select className="field-control" value={draft.kind} onChange={event => onChange({ ...draft, kind: event.target.value as Draft['kind'] })}>
            <option value="video">{t('presets.kindVideo')}</option>
            <option value="image">{t('presets.kindImage')}</option>
          </select>
        </label>
      </div>
      <label className="block">
        <span className="field-label">{t('presets.description')}</span>
        <input className="field-control" value={draft.description} maxLength={280} onChange={event => onChange({ ...draft, description: event.target.value })} />
      </label>
      <label className="block">
        <span className="field-label">{t('presets.options')}</span>
        <textarea
          className="field-control h-44 py-2 font-mono leading-relaxed"
          spellCheck={false}
          value={draft.optionsText}
          onChange={event => onChange({ ...draft, optionsText: event.target.value })}
        />
        <span className="mt-1 block text-[11px] text-text-muted">{t('presets.optionsHint')}</span>
      </label>
      {error && <p role="alert" className="text-xs text-accent">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onCancel}>{t('presets.cancel')}</button>
        <button type="submit" className="btn-primary" disabled={saving || !draft.name.trim()}>{t('presets.save')}</button>
      </div>
    </form>
  )
}

function Presets() {
  const { t } = useTranslation()
  const [presets, setPresets] = useState<Preset[]>([])
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Preset | null>(null)

  const refresh = () => listPresets()
    .then(setPresets)
    .catch(err => setError(err instanceof Error ? err.message : t('presets.loadFailed')))
    .finally(() => setLoading(false))

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async () => {
    if (!draft) return
    let options: EncodeOptions
    try {
      options = JSON.parse(draft.optionsText || '{}')
    } catch {
      setError(t('presets.invalidJson'))
      return
    }
    setSaving(true)
    setError(null)
    try {
      const payload = { name: draft.name.trim(), description: draft.description.trim() || null, kind: draft.kind, options }
      if (draft.id) await updatePreset(draft.id, payload)
      else await createPreset(payload)
      setDraft(null)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('presets.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  const edit = (preset: Preset, copy = false) => {
    setError(null)
    setDraft({
      id: copy ? undefined : preset.id,
      name: copy ? t('presets.copyName', { name: preset.name }) : preset.name,
      description: preset.description ?? '',
      kind: preset.kind,
      optionsText: JSON.stringify(preset.options, null, 2),
    })
  }

  const builtins = presets.filter(p => p.builtin)
  const saved = presets.filter(p => !p.builtin)

  const card = (preset: Preset) => (
    <li key={preset.id} className="panel flex flex-col gap-2 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-text">{preset.name}</p>
          <p className="font-mono text-[11px] text-text-muted">{preset.id} · {preset.kind === 'video' ? t('presets.kindVideo') : t('presets.kindImage')}</p>
        </div>
        <div className="flex shrink-0">
          <button type="button" className="rounded p-1.5 text-text-muted hover:bg-text/10 hover:text-text" onClick={() => edit(preset, true)} aria-label={t('presets.duplicate')} title={t('presets.duplicate')}>
            <FaCopy className="text-xs" />
          </button>
          {!preset.builtin && (
            <>
              <button type="button" className="rounded p-1.5 text-text-muted hover:bg-text/10 hover:text-text" onClick={() => edit(preset)} aria-label={t('presets.edit')} title={t('presets.edit')}>
                <FaPenToSquare className="text-xs" />
              </button>
              <button type="button" className="rounded p-1.5 text-text-muted hover:bg-text/10 hover:text-accent" onClick={() => setPendingDelete(preset)} aria-label={t('presets.delete')} title={t('presets.delete')}>
                <FaTrashCan className="text-xs" />
              </button>
            </>
          )}
        </div>
      </div>
      {preset.description && <p className="text-xs text-text-muted">{preset.description}</p>}
      <pre className="whitespace-pre-wrap break-all rounded border border-text/10 bg-surface-dark px-2 py-1.5 font-mono text-[11px] text-text-muted">
        {JSON.stringify(preset.options)}
      </pre>
    </li>
  )

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-medium text-text">{t('presets.title')}</h1>
          <p className="text-sm text-text-muted">{t('presets.subtitle')}</p>
        </div>
        {!draft && (
          <button type="button" className="btn-primary" onClick={() => { setError(null); setDraft(EMPTY_DRAFT) }}>
            <FaPlus /> {t('presets.new')}
          </button>
        )}
      </div>

      {draft && (
        <PresetEditor draft={draft} onChange={setDraft} onSave={save} onCancel={() => setDraft(null)} saving={saving} error={error} />
      )}
      {!draft && error && <p role="alert" className="text-xs text-accent">{error}</p>}

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-text">{t('presets.saved')}</h2>
        {loading ? null : saved.length === 0 ? (
          <p className="text-sm text-text-muted">{t('presets.savedEmpty')}</p>
        ) : (
          <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">{saved.map(card)}</ul>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-text">{t('presets.builtin')}</h2>
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">{builtins.map(card)}</ul>
      </section>

      <ConfirmDialog
        isOpen={pendingDelete !== null}
        title={t('presets.deleteTitle')}
        message={t('presets.deleteMessage', { name: pendingDelete?.name ?? '' })}
        confirmLabel={t('presets.delete')}
        cancelLabel={t('presets.cancel')}
        isDestructive
        onCancel={() => setPendingDelete(null)}
        onConfirm={async () => {
          const target = pendingDelete
          setPendingDelete(null)
          if (!target) return
          try {
            await deletePreset(target.id)
            await refresh()
          } catch (err) {
            setError(err instanceof Error ? err.message : t('presets.deleteFailed'))
          }
        }}
      />
    </div>
  )
}

export default Presets
