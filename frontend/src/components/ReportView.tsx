import { ArrowLeft, Braces, LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, reportJsonUrl } from '../api/client'
import { Button } from './ui/button'
import { Callout } from './ui/callout'

// Element styles for the server's Markdown report (raw HTML in the Markdown is not rendered).
const MD: Components = {
  h1: (p) => <h1 className="mb-4 text-xl font-semibold leading-snug tracking-tight text-fg" {...p} />,
  h2: (p) => <h2 className="mb-2 mt-8 border-b border-line pb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-subtle" {...p} />,
  h3: (p) => <h3 className="mb-1 mt-5 font-semibold text-fg" {...p} />,
  p: (p) => <p className="my-2.5 leading-relaxed" {...p} />,
  strong: (p) => <strong className="font-semibold text-fg" {...p} />,
  ul: (p) => <ul className="my-2.5 list-disc space-y-1.5 pl-5 marker:text-fg-subtle" {...p} />,
  ol: (p) => <ol className="my-2.5 list-decimal space-y-1.5 pl-5 marker:text-fg-subtle" {...p} />,
  a: ({ href, ...p }) => <a href={href} target="_blank" rel="noreferrer" className="text-accent-strong underline underline-offset-2" {...p} />,
  code: (p) => <code className="break-words rounded bg-raised px-1 py-0.5 font-mono text-[0.85em] text-fg" {...p} />,
  pre: (p) => <pre className="my-3 overflow-x-auto rounded-[var(--radius-control)] border border-line bg-canvas p-3 text-xs" {...p} />,
  blockquote: (p) => <blockquote className="my-3 border-l-2 border-warn/60 pl-3 text-fg-muted" {...p} />,
  table: (p) => (
    <div className="my-4 overflow-x-auto rounded-[var(--radius-control)] border border-line">
      <table className="w-full border-collapse text-left text-xs" {...p} />
    </div>
  ),
  thead: (p) => <thead className="bg-raised" {...p} />,
  th: (p) => <th className="border-b border-line px-3 py-2 font-semibold text-fg" {...p} />,
  td: (p) => <td className="border-b border-line/70 px-3 py-2 align-top" {...p} />,
  img: ({ src, alt }) => <img src={typeof src === 'string' ? src : undefined} alt={alt ?? ''} className="my-3 max-w-full rounded-[var(--radius-control)] border border-line" />,
  hr: () => <hr className="my-6 border-line" />,
}

/** The saved report exactly as the server wrote it, rendered from Markdown. */
export function ReportView({ inspectionId, onBack }: { inspectionId: string; onBack: () => void }) {
  const [md, setMd] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    api.reportMarkdown(inspectionId)
      .then((t) => live && setMd(t))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [inspectionId])
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" className="-ml-3" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Back to inspection</Button>
        <a href={reportJsonUrl(inspectionId)} target="_blank" rel="noreferrer"
          className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line-strong px-3 text-[13px] text-fg-muted transition-colors duration-150 hover:text-fg">
          <Braces className="h-3.5 w-3.5" aria-hidden /> JSON
        </a>
      </div>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-subtle">Audit report</p>
        <p className="mt-1 text-sm text-fg-muted">Exactly as saved on the server, with every verdict, photo and model call.</p>
      </div>
      <article aria-label="Saved report" className="rounded-[var(--radius-panel)] border border-line bg-surface px-4 py-5 text-sm text-fg-muted sm:px-6">
        {error ? <Callout tone="error" title="Could not load the report">{error}</Callout>
          : md === null ? <p className="flex items-center gap-2 text-fg-subtle"><LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> Loading report…</p>
          : <Markdown remarkPlugins={[remarkGfm]} components={MD}>{md}</Markdown>}
      </article>
    </div>
  )
}
