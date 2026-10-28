import { useState } from 'react'
import { FaCheck, FaCode } from 'react-icons/fa6'
import { useTranslation } from 'react-i18next'
import { curlCommand, type JobRequest } from './model'

export default function ApiPreview({ request }: { request: JobRequest }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(curlCommand(request))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border border-text/10 bg-surface-dark">
      <div className="flex items-center justify-between gap-2 border-b border-text/10 px-3 py-2">
        <span className="font-mono text-[11px] text-text-muted">
          <span className="text-primary">POST</span> {request.endpoint}
        </span>
        <button type="button" onClick={copy} className="btn h-7 px-2 text-[11px]">
          {copied ? <FaCheck className="text-primary" /> : <FaCode />}
          {copied ? t('workspace.api.copied') : t('workspace.api.copyCurl')}
        </button>
      </div>
      <pre className="max-h-64 overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed text-text-muted">
        {JSON.stringify(request.body, null, 2)}
      </pre>
    </div>
  )
}
