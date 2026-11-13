import { cloneElement, isValidElement, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type CSSProperties, type ReactNode, type RefObject } from 'react'
import { clsx } from 'clsx'
import { Check, ChevronLeft, ChevronRight, Copy, Loader2, Plus, X, type LucideIcon } from 'lucide-react'

// ---------------------------------------------------------------- tones
export type Tone = 'neutral' | 'muted' | 'accent' | 'good' | 'warn' | 'bad' | 'violet' | 'aqua' | 'serious'

export function toneStyle(tone: Tone): CSSProperties {
  const map: Record<Tone, { bg: string; fg: string }> = {
    neutral: { bg: 'var(--surface-2)', fg: 'var(--ink-2)' },
    muted: { bg: 'transparent', fg: 'var(--muted)' },
    accent: { bg: 'color-mix(in oklab, var(--accent) 14%, transparent)', fg: 'var(--accent-ink)' },
    good: { bg: 'color-mix(in oklab, var(--good) 14%, transparent)', fg: 'var(--good-ink)' },
    warn: { bg: 'color-mix(in oklab, var(--warn) 18%, transparent)', fg: 'var(--warn-ink)' },
    bad: { bg: 'color-mix(in oklab, var(--bad) 13%, transparent)', fg: 'var(--bad-ink)' },
    violet: { bg: 'color-mix(in oklab, var(--violet) 14%, transparent)', fg: 'var(--violet-ink)' },
    aqua: { bg: 'color-mix(in oklab, var(--aqua) 14%, transparent)', fg: 'var(--aqua-ink)' },
    serious: { bg: 'color-mix(in oklab, var(--serious) 16%, transparent)', fg: 'var(--serious-ink)' },
  }
  const t = map[tone]
  return { background: t.bg, color: t.fg, boxShadow: tone === 'muted' ? 'inset 0 0 0 1px var(--line)' : undefined }
}

// ---------------------------------------------------------------- button
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline'
interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  icon?: LucideIcon
}
export function Button({ variant = 'secondary', size = 'md', loading, icon: Icon, className, children, disabled, ...rest }: ButtonProps) {
  const base = 'inline-flex items-center justify-center gap-1.5 rounded-[9px] font-semibold transition-colors whitespace-nowrap select-none disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40'
  const sizes = size === 'sm' ? 'h-8 px-3 text-xs' : size === 'lg' ? 'h-11 px-5 text-sm' : 'h-10 px-4 text-sm'
  const variants: Record<Variant, string> = {
    primary: 'bg-accent text-on-accent hover:brightness-110',
    secondary: 'bg-surface-2 text-ink hover:bg-surface-3',
    outline: 'border border-line bg-surface text-ink hover:bg-surface-2',
    ghost: 'text-ink-2 hover:bg-surface-2 hover:text-ink',
    danger: 'bg-bad text-white hover:brightness-110',
  }
  return (
    <button className={clsx(base, sizes, variants[variant], className)} disabled={disabled || loading} {...rest}>
      {loading ? <Loader2 size={size === 'sm' ? 13 : 15} className="spin" /> : Icon ? <Icon size={size === 'sm' ? 13 : 15} /> : null}
      {children}
    </button>
  )
}

// ---------------------------------------------------------------- chip
export function Chip({ tone = 'neutral', children, className, title, dot }: { tone?: Tone; children: ReactNode; className?: string; title?: string; dot?: boolean }) {
  return (
    <span title={title} style={toneStyle(tone)} className={clsx('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap', className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

// ---------------------------------------------------------------- card
export function Card({ title, subtitle, actions, children, className, padded = true }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={clsx('card overflow-hidden', className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-2">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx(padded && 'p-4')}>{children}</div>
    </section>
  )
}

export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return <Loader2 size={size} className={clsx('spin text-muted', className)} />
}

export function EmptyState({ icon: Icon, title, hint, action }: { icon?: LucideIcon; title: string; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {Icon && <Icon size={28} className="text-muted" />}
      <div className="font-medium">{title}</div>
      {hint && <div className="max-w-md text-xs text-ink-2">{hint}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- form bits
export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  // A <label> passes clicks on its text to its first control, which in a ListEditor is a chip's Remove button.
  if (isValidElement<ListEditorProps>(children) && children.type === ListEditor) {
    const name = typeof label === 'string' ? label : undefined
    return (
      <div className={clsx('block', className)}>
        <div className="mb-1 text-xs font-medium text-ink-2">{label}</div>
        {name && !children.props.ariaLabel ? cloneElement(children, { ariaLabel: name }) : children}
        {hint && <div className="mt-1 text-[11px] text-muted">{hint}</div>}
      </div>
    )
  }
  return (
    <label className={clsx('block', className)}>
      <div className="mb-1 text-xs font-medium text-ink-2">{label}</div>
      {children}
      {hint && <div className="mt-1 text-[11px] text-muted">{hint}</div>}
    </label>
  )
}

/** Without a visible `label`, pass `ariaLabel` so screen readers can name it. */
export function Switch({ checked, onChange, disabled, label, ariaLabel }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: ReactNode; ariaLabel?: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={ariaLabel} disabled={disabled} onClick={() => onChange(!checked)}
      className={clsx('inline-flex shrink-0 items-center gap-2 text-left disabled:opacity-50', label && 'text-sm')}>
      <span className={clsx('relative inline-block h-5 w-9 rounded-full transition-colors', checked ? 'bg-accent' : 'bg-surface-3')}>
        <span className={clsx('absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform', checked ? 'translate-x-4' : 'translate-x-0')} />
      </span>
      {label}
    </button>
  )
}

interface ListEditorProps { value: string[]; onChange: (v: string[]) => void; placeholder?: string; className?: string; ariaLabel?: string }
export function ListEditor({ value, onChange, placeholder, className, ariaLabel }: ListEditorProps) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const parts = draft.split(',').map((s) => s.trim()).filter(Boolean)
    if (!parts.length) return
    const next = [...value]
    for (const p of parts) if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p)
    onChange(next)
    setDraft('')
  }
  return (
    <div className={clsx('rounded-lg border border-line bg-surface p-2', className)}>
      <div className="flex flex-wrap gap-1.5">
        {value.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-md bg-surface-2 px-2 py-0.5 text-xs">
            {v}
            <button type="button" className="text-muted hover:text-ink" onClick={() => onChange(value.filter((x) => x !== v))} aria-label={`Remove ${v}`}>
              <X size={12} />
            </button>
          </span>
        ))}
        {!value.length && <span className="px-1 text-xs text-muted">Nothing yet</span>}
      </div>
      <div className="mt-2 flex gap-2">
        <input className="input !py-1.5 text-xs" aria-label={ariaLabel} value={draft} placeholder={placeholder ?? 'Type and press Enter (comma separates several)'} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
        <Button size="sm" icon={Plus} onClick={add} type="button">Add</Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- tabs
export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: Array<{ value: T; label: ReactNode; count?: number }> }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 rounded-lg bg-surface-2 p-1">
      {items.map((it) => (
        <button key={it.value} type="button" role="tab" aria-selected={value === it.value} onClick={() => onChange(it.value)}
          className={clsx('inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors', value === it.value ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink')}>
          {it.label}
          {it.count !== undefined && <span className={clsx('num rounded-full px-1.5 text-[10px]', value === it.value ? 'bg-surface-2' : 'bg-surface')}>{it.count}</span>}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- pagination
export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-between gap-3 text-xs text-ink-2">
      <span className="num">{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}</span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" icon={ChevronLeft} disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page" />
        <span className="num px-1">{page} / {pages}</span>
        <Button size="sm" variant="ghost" icon={ChevronRight} disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Next page" />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- key/value
export function KV({ rows }: { rows: Array<[ReactNode, ReactNode]> }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-xs text-ink-2 leading-6">{k}</dt>
          <dd className="min-w-0 break-words leading-6">{v ?? <span className="text-muted">—</span>}</dd>
        </div>
      ))}
    </dl>
  )
}

// ---------------------------------------------------------------- dialog & drawer
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
const openModals: object[] = []

/** Focus moves into the modal on open, Tab stays inside it, Escape closes only the topmost one, and focus returns to the opener on close. */
export function useModal(open: boolean, ref: RefObject<HTMLElement | null>, onClose: () => void) {
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose })
  useEffect(() => {
    const root = ref.current
    if (!open || !root) return
    const token = {}
    openModals.push(token)
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!root.contains(document.activeElement)) root.focus()           // keeps an autoFocus field focused
    const onKey = (e: KeyboardEvent) => {
      if (openModals[openModals.length - 1] !== token) return
      if (e.key === 'Escape') { e.preventDefault(); close.current(); return }
      if (e.key !== 'Tab') return
      const els = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.getClientRects().length > 0)
      const active = document.activeElement
      if (!els.length) { e.preventDefault(); root.focus(); return }
      const [first, last] = [els[0], els[els.length - 1]]
      const outside = !root.contains(active) || active === root
      if (e.shiftKey ? outside || active === first : outside || active === last) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      openModals.splice(openModals.indexOf(token), 1)
      if (opener?.isConnected) opener.focus()
    }
  }, [open, ref])
}

export function Dialog({ open, title, children, onClose, footer }: { open: boolean; title: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useModal(open, ref, onClose)
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/40 p-4" onMouseDown={onClose}>
      <div ref={ref} role="dialog" aria-modal aria-labelledby={titleId} tabIndex={-1} className="card w-full max-w-md shadow-[var(--shadow)] outline-none" onMouseDown={(e) => e.stopPropagation()}>
        <div id={titleId} className="border-b border-line px-4 py-3 text-sm font-semibold">{title}</div>
        <div className="scroll-thin max-h-[calc(100dvh-10rem)] overflow-y-auto px-4 py-3 text-sm">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  )
}

export function Drawer({ open, onClose, title, children, width = 720, actions }: { open: boolean; onClose: () => void; title?: ReactNode; children: ReactNode; width?: number; actions?: ReactNode }) {
  const ref = useRef<HTMLElement>(null)
  const titleId = useId()
  useModal(open, ref, onClose)
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[80] bg-black/30" onMouseDown={onClose}>
      <aside ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="drawer-in absolute right-0 top-0 flex h-full flex-col border-l border-line bg-surface shadow-[var(--shadow)] outline-none"
        style={{ width: `min(${width}px, 100vw)` }} onMouseDown={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <div id={titleId} className="min-w-0 flex-1 text-sm font-semibold">{title}</div>
          <div className="flex items-center gap-2">
            {actions}
            <button onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close"><X size={16} /></button>
          </div>
        </header>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">{children}</div>
      </aside>
    </div>
  )
}

// ---------------------------------------------------------------- log view
export function LogView({ text, lines, maxHeight = 320, className }: { text?: string | null; lines?: string[]; maxHeight?: number; className?: string }) {
  const ref = useRef<HTMLPreElement>(null)
  const content = lines ? lines.join('\n') : (text ?? '')
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [content])
  if (!content.trim()) return <div className="text-xs text-muted">No log output.</div>
  return (
    <pre ref={ref} className={clsx('mono scroll-thin overflow-auto rounded-lg bg-surface-2 p-3 leading-5 whitespace-pre-wrap break-words', className)} style={{ maxHeight }}>
      {content}
    </pre>
  )
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <Button size="sm" variant="outline" icon={done ? Check : Copy} onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500) } catch { /* clipboard blocked */ }
    }}>{done ? 'Copied' : label}</Button>
  )
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-2">{children}</h3>
      {right}
    </div>
  )
}
