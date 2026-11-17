import {
  Badge,
  Button,
  Checkbox,
  Dropdown,
  Input,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Tab,
  TabList,
  Text,
} from '@fluentui/react-components'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'

import { inferSchema, useAddSchema, useEntities, useEntity, useSchema, useSchemas } from '../api/hooks'
import type { JsonSchema, SchemaReference } from '../api/types'
import { ErrorBar, JsonField } from '../components/forms'
import { Page } from '../components/Shell'
import { applyRefRows, type RefRow, refRows, unpinRefs } from '../editor/entityRefs'
import { describeTypes, listFields } from '../editor/schemaPaths'
import { useI18n } from '../i18n'

function EntityBadge({ ws, entity, version }: { ws: string; entity: string; version?: number }) {
  return (
    <Link to={`/w/${ws}/entities/${entity}`} className="badge-gap">
      <Badge size="small" appearance="outline" color="brand">
        {version ? `${entity} v${version}` : entity}
      </Badge>
    </Link>
  )
}

function FieldTree({ ws, schema }: { ws: string; schema: JsonSchema | undefined }) {
  const fields = useMemo(() => listFields(schema), [schema])
  const { t } = useI18n()
  if (!schema) return null
  if (fields.length === 0) return <Text>{t('entity.noFields')}</Text>
  return (
    <div className="table-scroll">
    <table className="field-table" aria-label={t('entity.fieldsTable')}>
      <thead>
        <tr>
          <th>{t('entity.field')}</th>
          <th>{t('entity.type')}</th>
          <th>{t('entity.reference')}</th>
        </tr>
      </thead>
      <tbody>
        {fields.map((f) => (
          <tr key={f.path}>
            <td style={{ paddingLeft: 8 + f.depth * 18 }}>
              {f.name}
              {f.required && (
                <Badge size="small" appearance="tint" className="badge-gap">
                  {t('entity.required')}
                </Badge>
              )}
              {f.entity && <EntityBadge ws={ws} {...f.entity} />}
            </td>
            <td>{describeTypes(f)}</td>
            <td>
              <code>{f.path}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}

function References({
  ws,
  references,
  usedBy,
  onUpdate,
  updating,
}: {
  ws: string
  references: SchemaReference[]
  usedBy: string[]
  onUpdate: () => void
  updating: boolean
}) {
  const { t } = useI18n()
  const stale = references.filter((r) => r.latest !== null && r.latest > r.version)
  if (references.length === 0 && usedBy.length === 0) return null
  return (
    <div className="stack">
      {references.length > 0 && (
        <Text>
          {t('entity.uses')}{' '}
          {references.map((r) => (
            <EntityBadge key={r.entity} ws={ws} entity={r.entity} version={r.version} />
          ))}
        </Text>
      )}
      {stale.length > 0 && (
        <MessageBar intent="warning">
          <MessageBarBody>
            {t('entity.staleRefs', { list: stale.map((r) => `${r.entity} v${r.latest}`).join(', ') })}{' '}
            <Button size="small" onClick={onUpdate} disabled={updating}>
              {t('entity.updateRefs')}
            </Button>
          </MessageBarBody>
        </MessageBar>
      )}
      {usedBy.length > 0 && (
        <Text>
          {t('entity.usedBy')}{' '}
          {usedBy.map((e) => (
            <EntityBadge key={e} ws={ws} entity={e} />
          ))}
        </Text>
      )}
    </div>
  )
}

function ComposeEditor({
  ws,
  self,
  rows,
  onChange,
}: {
  ws: string
  self: string
  rows: RefRow[]
  onChange: (rows: RefRow[]) => void
}) {
  const entities = useEntities(ws)
  const { t } = useI18n()
  const others = (entities.data ?? []).filter((e) => e.key !== self)
  const set = (i: number, patch: Partial<RefRow>) => onChange(rows.map((r, n) => (n === i ? { ...r, ...patch } : r)))
  return (
    <div className="stack">
      <Text>{t('entity.composeHint')}</Text>
      <div className="table-scroll">
        <table className="field-table" aria-label={t('entity.composeTable')}>
          <thead>
            <tr>
              <th>{t('entity.field')}</th>
              <th>{t('entity.entity')}</th>
              <th>{t('entity.list')}</th>
              <th>{t('entity.required')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>
                  <Input
                    aria-label={t('entity.field')}
                    value={r.name}
                    onChange={(_, d) => set(i, { name: d.value })}
                  />
                </td>
                <td>
                  <Dropdown
                    aria-label={t('entity.entity')}
                    value={r.entity}
                    selectedOptions={[r.entity]}
                    onOptionSelect={(_, d) => set(i, { entity: d.optionValue ?? '' })}
                  >
                    {others.map((e) => (
                      <Option key={e.key} value={e.key} text={e.key}>
                        {e.name === e.key ? e.key : `${e.key} · ${e.name}`}
                      </Option>
                    ))}
                  </Dropdown>
                </td>
                <td>
                  <Checkbox
                    aria-label={t('entity.list')}
                    checked={r.many}
                    onChange={(_, d) => set(i, { many: Boolean(d.checked) })}
                  />
                </td>
                <td>
                  <Checkbox
                    aria-label={t('entity.required')}
                    checked={r.required}
                    onChange={(_, d) => set(i, { required: Boolean(d.checked) })}
                  />
                </td>
                <td>
                  <Button appearance="subtle" onClick={() => onChange(rows.filter((_, n) => n !== i))}>
                    {t('common.remove')}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <Button onClick={() => onChange([...rows, { name: '', entity: '', many: false, required: true }])}>
          {t('entity.addField')}
        </Button>
      </div>
    </div>
  )
}

type Mode = 'view' | 'samples' | 'manual' | 'compose'

export function EntityPage() {
  const { ws, entity } = useParams() as { ws: string; entity: string }
  const info = useEntity(ws, entity)
  const versions = useSchemas(ws, entity)
  const [selected, setSelected] = useState<number | null>(null)
  const latest = versions.data?.[0]?.version ?? null
  const current = useSchema(ws, entity, selected ?? latest)
  const add = useAddSchema(ws, entity)
  const { t } = useI18n()

  const [chosenMode, setMode] = useState<Mode>('view')
  // An entity without schema versions opens directly on "from samples".
  const mode: Mode = chosenMode === 'view' && versions.data?.length === 0 ? 'samples' : chosenMode
  const [samples, setSamples] = useState<unknown>([{}])
  const [preview, setPreview] = useState<JsonSchema | undefined>()
  const [previewError, setPreviewError] = useState<unknown>(null)
  const [manual, setManual] = useState<unknown>(null)
  const [rows, setRows] = useState<RefRow[]>([])

  useEffect(() => {
    if (mode !== 'samples') return
    const list = Array.isArray(samples) ? samples : [samples]
    const handle = setTimeout(() => {
      inferSchema(list, entity)
        .then((s) => {
          setPreview(s)
          setPreviewError(null)
        })
        .catch((e: unknown) => setPreviewError(e))
    }, 300)
    return () => clearTimeout(handle)
  }, [samples, mode, entity])

  async function store(body: { schema: JsonSchema } | { samples: unknown[] }) {
    const saved = await add.mutateAsync(body)
    setSelected(saved.version)
    setMode('view')
  }

  function save() {
    if (mode === 'samples') return store({ samples: Array.isArray(samples) ? samples : [samples] })
    if (mode === 'compose') return store({ schema: applyRefRows(current.data?.schema, rows) })
    return store({ schema: manual as JsonSchema })
  }

  const composeInvalid = mode === 'compose' && rows.some((r) => !r.name.trim() || !r.entity)

  return (
    <Page
      title={t('entity.title', { entity })}
      actions={
        mode === 'view' ? (
          <>
            <Button onClick={() => setMode('samples')}>{t('entity.newFromSamples')}</Button>
            <Button
              onClick={() => {
                const found = refRows(current.data?.schema)
                setRows(found.length > 0 ? found : [{ name: '', entity: '', many: false, required: true }])
                setMode('compose')
              }}
            >
              {t('entity.compose')}
            </Button>
            <Button
              onClick={() => {
                setManual(current.data?.schema ?? { type: 'object', properties: {} })
                setMode('manual')
              }}
            >
              {t('entity.editSchema')}
            </Button>
          </>
        ) : (
          <>
            <Button onClick={() => setMode('view')}>{t('common.cancel')}</Button>
            <Button
              appearance="primary"
              onClick={() => void save()}
              disabled={add.isPending || (mode === 'samples' && !preview) || composeInvalid}
            >
              {t('entity.saveVersion')}
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
            aria-label={t('entity.versions')}
          >
            {versions.data.map((v) => (
              <Tab key={v.version} value={String(v.version)}>
                v{v.version} · {v.source === 'sample' ? t('entity.fromSamples') : v.source}
              </Tab>
            ))}
          </TabList>
          {current.isLoading && <Spinner size="tiny" />}
          <References
            ws={ws}
            references={current.data?.references ?? []}
            usedBy={info.data?.usedBy ?? []}
            updating={add.isPending}
            onUpdate={() => current.data?.schema && void store({ schema: unpinRefs(current.data.schema) })}
          />
          <FieldTree ws={ws} schema={current.data?.resolved ?? current.data?.schema} />
        </div>
      )}

      {mode === 'samples' && (
        <div className="two-col">
          <JsonField
            label={t('entity.samples')}
            hint={t('entity.samplesHint')}
            value={samples}
            onValid={setSamples}
            rows={22}
          />
          <div className="stack">
            <Text weight="semibold">{t('entity.preview')}</Text>
            <ErrorBar error={previewError} />
            <FieldTree ws={ws} schema={preview} />
          </div>
        </div>
      )}

      {mode === 'compose' && <ComposeEditor ws={ws} self={entity} rows={rows} onChange={setRows} />}

      {mode === 'manual' && (
        <JsonField
          label={t('entity.jsonSchema')}
          hint={t('entity.jsonSchemaHint')}
          value={manual}
          onValid={setManual}
          rows={28}
        />
      )}
    </Page>
  )
}
