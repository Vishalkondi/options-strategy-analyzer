import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { StrategySpec, CreatedStrategy } from '../lib/api'
import { Card, CardTitle, CardSubtitle, Button, Spinner, Pill } from '../components/ui'

export function StrategyBuilderPage() {
  const [baseStrategies, setBaseStrategies] = useState<StrategySpec[]>([])
  const [parentFile, setParentFile] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<CreatedStrategy | null>(null)

  useEffect(() => {
    api.strategies().then((s) => {
      setBaseStrategies(s)
      if (s.length) {
        setParentFile(s[0].file)
        setOverrides(Object.fromEntries(Object.entries(s[0].parameters).map(([k, v]) => [k, v.default])))
      }
    })
  }, [])

  const parent = baseStrategies.find((s) => s.file === parentFile)

  function onParentChange(file: string) {
    setParentFile(file)
    const p = baseStrategies.find((s) => s.file === file)
    if (p) setOverrides(Object.fromEntries(Object.entries(p.parameters).map(([k, v]) => [k, v.default])))
  }

  async function handleSave() {
    if (!name.trim() || !parentFile) return
    setSaving(true)
    setError(null)
    setSaved(null)
    try {
      const result = await api.createStrategy({
        name: name.trim(),
        description: description.trim() || undefined,
        parent_file: parentFile,
        parameters: overrides,
      })
      setSaved(result)
      setName('')
      setDescription('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <span className="font-mono text-[11px] uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>Strategy workshop</span>
        <h2 className="font-display font-bold text-2xl mt-1 mb-1" style={{ color: 'var(--color-ink)' }}>Strategy Builder</h2>
        <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
          Builds a new, named, versioned strategy from the existing engine's parameter schema — not a second
          engine. Save it here, then it's immediately available in Strategy Runner and Live Monitor, exactly
          like any hand-written strategy file.
        </p>
      </div>

      {baseStrategies.length === 0 ? (
        <Card><p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>No base strategies registered yet.</p></Card>
      ) : (
        <>
          <Card>
            <CardTitle>Base engine</CardTitle>
            <CardSubtitle>The rule structure (SMA crossover, ADX-gated) is reused as-is — you're tuning its parameters.</CardSubtitle>
            <select
              value={parentFile}
              onChange={(e) => onParentChange(e.target.value)}
              className="w-full rounded-lg border px-3.5 py-2 text-[13.5px] outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
            >
              {baseStrategies.map((s) => <option key={s.file} value={s.file}>{s.name} (v{s.version})</option>)}
            </select>
          </Card>

          <Card>
            <CardTitle>Name your build</CardTitle>
            <div className="space-y-3">
              <input
                value={name} onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Fast Momentum, High Conviction ADX"
                className="w-full rounded-lg border px-3.5 py-2 text-[13.5px] outline-none"
                style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
              />
              <input
                value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description"
                className="w-full rounded-lg border px-3.5 py-2 text-[13.5px] outline-none"
                style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
              />
            </div>
          </Card>

          {parent && (
            <Card>
              <CardTitle>Parameters</CardTitle>
              <CardSubtitle>Set the defaults for this build.</CardSubtitle>
              <div className="grid grid-cols-2 gap-4">
                {Object.entries(parent.parameters).map(([key, spec]) => (
                  <div key={key}>
                    <label className="text-[11px] uppercase tracking-wider mb-1 block font-mono" style={{ color: 'var(--color-ink-faint)' }}>{key}</label>
                    <input
                      type="number" step="any" min={spec.min} max={spec.max}
                      value={overrides[key] ?? spec.default}
                      onChange={(e) => setOverrides((p) => ({ ...p, [key]: Number(e.target.value) }))}
                      className="w-full rounded-lg border px-3 py-1.5 text-[13px] font-mono outline-none"
                      style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
                    />
                    {spec.description && (
                      <div className="text-[11px] mt-1" style={{ color: 'var(--color-warn)' }}>{spec.description}</div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Button onClick={handleSave} disabled={saving || !name.trim()} className="w-full py-3">
            {saving ? <Spinner size={14} /> : null} Save as new strategy
          </Button>
          {error && <div className="text-[13px]" style={{ color: 'var(--color-loss)' }}>{error}</div>}

          {saved && (
            <Card>
              <div className="flex items-center justify-between mb-2">
                <CardTitle>Saved</CardTitle>
                <Pill tone="accent">{saved.file}</Pill>
              </div>
              <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
                "{saved.name}" (v{saved.version}) is now runnable from Strategy Runner and watchable from Live Monitor.
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
