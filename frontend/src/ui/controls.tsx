/*
  Small, text-free controls for dense tool panels. Callers pass every label,
  so these stay outside the i18n-scanned component folders.
*/
import type { ReactNode } from 'react'

export interface SegmentOption<T extends string | number> {
  value: T
  label: ReactNode
  disabled?: boolean
  hint?: string
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  ariaLabel,
  mono = false,
}: {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  ariaLabel: string
  mono?: boolean
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="flex gap-0.5 rounded-md border border-text/10 bg-surface-dark p-0.5">
      {options.map(option => {
        const active = option.value === value
        return (
          <button
            key={String(option.value)}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={option.disabled}
            title={option.hint}
            onClick={() => onChange(option.value)}
            className={`min-w-0 flex-1 truncate rounded px-2 py-1 text-xs transition ${mono ? 'font-mono' : ''} ${
              active
                ? 'bg-text/15 text-text'
                : 'text-text-muted hover:text-text disabled:cursor-not-allowed disabled:text-text-muted/40 disabled:hover:text-text-muted/40'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

export function Field({ label, children, className = '', group = false }: {
  label: ReactNode
  children: ReactNode
  className?: string
  /** Wrap a group of buttons: a <label> would forward clicks to the first one. */
  group?: boolean
}) {
  if (group) {
    return (
      <div className={`min-w-0 ${className}`}>
        <span className="field-label">{label}</span>
        {children}
      </div>
    )
  }
  return (
    <label className={`block min-w-0 ${className}`}>
      <span className="field-label">{label}</span>
      {children}
    </label>
  )
}

/**
 * A slider whose "unset" state means "inherit" (preset, legacy preset, or
 * encoder default). The thumb sits at ``fallback`` until the user moves it.
 */
export function AutoSlider({
  label,
  value,
  fallback,
  min,
  max,
  step = 1,
  onChange,
  autoText,
  resetLabel,
  format = v => String(v),
  disabled = false,
}: {
  label: ReactNode
  value: number | undefined
  fallback: number
  min: number
  max: number
  step?: number
  onChange: (value: number | undefined) => void
  autoText: string
  resetLabel: string
  format?: (value: number) => string
  disabled?: boolean
}) {
  const shown = value ?? fallback
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 shrink-0 text-xs text-text-muted">{label}</span>
      <input
        type="range"
        className="min-w-0 flex-1"
        min={min}
        max={max}
        step={step}
        value={shown}
        disabled={disabled}
        onChange={event => onChange(Number(event.target.value))}
        aria-label={typeof label === 'string' ? label : undefined}
        aria-valuetext={value === undefined ? autoText : format(shown)}
      />
      <span className="flex w-24 shrink-0 items-center justify-end gap-1 font-mono text-xs tabular-nums">
        {value === undefined ? (
          <span className="text-text-muted">{autoText}</span>
        ) : (
          <>
            <span>{format(value)}</span>
            <button
              type="button"
              onClick={() => onChange(undefined)}
              aria-label={resetLabel}
              title={resetLabel}
              className="rounded px-1 text-text-muted hover:text-text"
            >
              ×
            </button>
          </>
        )}
      </span>
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  children,
  disabled = false,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  children: ReactNode
  disabled?: boolean
}) {
  return (
    <label className={`flex cursor-pointer items-center gap-2 text-xs text-text ${disabled ? 'cursor-not-allowed opacity-40' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={event => onChange(event.target.checked)}
        className="h-3.5 w-3.5 rounded border-text/20"
      />
      {children}
    </label>
  )
}

export function ProgressBar({ percent, tone = 'primary' }: { percent: number | null | undefined; tone?: 'primary' | 'muted' }) {
  const width = percent == null ? 0 : Math.max(0, Math.min(100, percent))
  const indeterminate = percent == null
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-text/10">
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${tone === 'primary' ? 'bg-primary' : 'bg-text-muted'} ${indeterminate ? 'w-1/3 animate-pulse' : ''}`}
        style={indeterminate ? undefined : { width: `${width}%` }}
      />
    </div>
  )
}
