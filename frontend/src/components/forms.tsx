// Small shared form pieces: error bar, create dialog, JSON text area.

import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Field,
  MessageBar,
  MessageBarBody,
  Textarea,
} from '@fluentui/react-components'
import { type FormEvent, type ReactElement, type ReactNode, useState } from 'react'

import { errorMessage } from '../api/client'

export function ErrorBar({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <MessageBar intent="error">
      <MessageBarBody>{errorMessage(error)}</MessageBarBody>
    </MessageBar>
  )
}

export function FormDialog({
  trigger,
  title,
  submitLabel,
  onSubmit,
  children,
  canSubmit = true,
}: {
  trigger: ReactElement
  title: string
  submitLabel: string
  onSubmit: () => Promise<unknown>
  children: ReactNode
  canSubmit?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit()
      setOpen(false)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(_, d) => setOpen(d.open)}>
      <DialogTrigger disableButtonEnhancement>{trigger}</DialogTrigger>
      <DialogSurface>
        <form onSubmit={submit}>
          <DialogBody>
            <DialogTitle>{title}</DialogTitle>
            <DialogContent className="stack">
              {children}
              <ErrorBar error={error} />
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary">Annulla</Button>
              </DialogTrigger>
              <Button appearance="primary" type="submit" disabled={busy || !canSubmit}>
                {submitLabel}
              </Button>
            </DialogActions>
          </DialogBody>
        </form>
      </DialogSurface>
    </Dialog>
  )
}

/**
 * A textarea holding JSON. `onValid` fires with the parsed value whenever the text parses;
 * the field shows the parse error otherwise. External value changes reset the text.
 */
export function JsonField({
  label,
  value,
  onValid,
  rows = 10,
  hint,
}: {
  label: string
  value: unknown
  onValid: (value: unknown) => void
  rows?: number
  hint?: string
}) {
  const serialised = JSON.stringify(value, null, 2) ?? ''
  const [text, setText] = useState(serialised)
  const [error, setError] = useState<string | null>(null)
  const [seen, setSeen] = useState(serialised)

  // Adopt a new external value (adjusting state during render, not in an effect), unless it
  // is just the echo of what the user typed.
  if (serialised !== seen) {
    setSeen(serialised)
    if (!isEcho(text, value)) {
      setText(serialised)
      setError(null)
    }
  }

  return (
    <Field
      label={label}
      validationState={error ? 'error' : 'none'}
      validationMessage={error ?? hint}
    >
      <Textarea
        className="mono"
        resize="vertical"
        rows={rows}
        value={text}
        onChange={(_, d) => {
          setText(d.value)
          try {
            const parsed: unknown = JSON.parse(d.value)
            setError(null)
            onValid(parsed)
          } catch (err) {
            setError(`JSON non valido: ${(err as Error).message}`)
          }
        }}
      />
    </Field>
  )
}

function isEcho(text: string, value: unknown): boolean {
  try {
    return JSON.stringify(JSON.parse(text)) === JSON.stringify(value)
  } catch {
    return false
  }
}

/** Slug-like key from a free-text name: "Piano di studi" -> "piano-di-studi". */
export function slugify(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9.]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}
