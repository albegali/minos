import {
  Badge,
  Button,
  Spinner,
  Tab,
  TabList,
  Text,
} from '@fluentui/react-components'
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'

import { errorMessage } from '../api/client'
import { inferSchema, useAddSchema, useSchema, useSchemas } from '../api/hooks'
import type { JsonSchema } from '../api/types'
import { ErrorBar, JsonField } from '../components/forms'
import { Page } from '../components/Shell'
import { describeTypes, listFields } from '../editor/schemaPaths'

function FieldTree({ schema }: { schema: JsonSchema | undefined }) {
  const fields = useMemo(() => listFields(schema), [schema])
  if (!schema) return null
  if (fields.length === 0) return <Text>Lo schema non dichiara campi.</Text>
  return (
    <table className="field-table" aria-label="Campi dello schema">
      <thead>
        <tr>
          <th>Campo</th>
          <th>Tipo</th>
          <th>Riferimento</th>
        </tr>
      </thead>
      <tbody>
        {fields.map((f) => (
          <tr key={f.path}>
            <td style={{ paddingLeft: 8 + f.depth * 18 }}>
              {f.name}
              {f.required && (
                <Badge size="small" appearance="tint" className="badge-gap">
                  obbligatorio
                </Badge>
              )}
            </td>
            <td>{describeTypes(f)}</td>
            <td>
              <code>{f.path}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

type Mode = 'view' | 'samples' | 'manual'

export function EntityPage() {
  const { ws, entity } = useParams() as { ws: string; entity: string }
  const versions = useSchemas(ws, entity)
  const [selected, setSelected] = useState<number | null>(null)
  const latest = versions.data?.[0]?.version ?? null
  const current = useSchema(ws, entity, selected ?? latest)
  const add = useAddSchema(ws, entity)

  const [chosenMode, setMode] = useState<Mode>('view')
  // An entity without schema versions opens directly on "from samples".
  const mode: Mode = chosenMode === 'view' && versions.data?.length === 0 ? 'samples' : chosenMode
  const [samples, setSamples] = useState<unknown>([{}])
  const [preview, setPreview] = useState<JsonSchema | undefined>()
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [manual, setManual] = useState<unknown>(null)

  useEffect(() => {
    if (mode !== 'samples') return
    const list = Array.isArray(samples) ? samples : [samples]
    const handle = setTimeout(() => {
      inferSchema(list, entity)
        .then((s) => {
          setPreview(s)
          setPreviewError(null)
        })
        .catch((e: unknown) => setPreviewError(errorMessage(e)))
    }, 300)
    return () => clearTimeout(handle)
  }, [samples, mode, entity])

  async function save() {
    const saved =
      mode === 'samples'
        ? await add.mutateAsync({ samples: Array.isArray(samples) ? samples : [samples] })
        : await add.mutateAsync({ schema: manual as JsonSchema })
    setSelected(saved.version)
    setMode('view')
  }

  return (
    <Page
      title={`Entità ${entity}`}
      actions={
        mode === 'view' ? (
          <>
            <Button onClick={() => setMode('samples')}>Nuova versione da esempi</Button>
            <Button
              onClick={() => {
                setManual(current.data?.schema ?? { type: 'object', properties: {} })
                setMode('manual')
              }}
            >
              Modifica JSON Schema
            </Button>
          </>
        ) : (
          <>
            <Button onClick={() => setMode('view')}>Annulla</Button>
            <Button appearance="primary" onClick={save} disabled={add.isPending || (mode === 'samples' && !preview)}>
              Salva come nuova versione
            </Button>
          </>
        )
      }
    >
      <ErrorBar error={versions.error ?? add.error} />
      {versions.isLoading && <Spinner />}

      {mode === 'view' && versions.data && versions.data.length > 0 && (
        <div className="stack">
          <TabList
            selectedValue={String(selected ?? latest)}
            onTabSelect={(_, d) => setSelected(Number(d.value))}
            aria-label="Versioni dello schema"
          >
            {versions.data.map((v) => (
              <Tab key={v.version} value={String(v.version)}>
                v{v.version} · {v.source === 'sample' ? 'da esempi' : v.source}
              </Tab>
            ))}
          </TabList>
          {current.isLoading && <Spinner size="tiny" />}
          <FieldTree schema={current.data?.schema} />
        </div>
      )}

      {mode === 'samples' && (
        <div className="two-col">
          <JsonField
            label="Esempi (un oggetto o una lista di oggetti)"
            hint="Più esempi rendono facoltativi i campi che non compaiono ovunque."
            value={samples}
            onValid={setSamples}
            rows={22}
          />
          <div className="stack">
            <Text weight="semibold">Anteprima dello schema</Text>
            {previewError && <ErrorBar error={new Error(previewError)} />}
            <FieldTree schema={preview} />
          </div>
        </div>
      )}

      {mode === 'manual' && (
        <JsonField
          label="JSON Schema (draft 2020-12)"
          value={manual}
          onValid={setManual}
          rows={28}
        />
      )}
    </Page>
  )
}
