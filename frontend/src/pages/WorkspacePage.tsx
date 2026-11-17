import {
  Button,
  Card,
  CardHeader,
  Dropdown,
  Field,
  Input,
  Option,
  Spinner,
  Text,
} from '@fluentui/react-components'
import { Add20Regular, ArrowUpload20Regular, Database20Regular, Flowchart20Regular } from '@fluentui/react-icons'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { importBundle, keys, useCreateEntity, useCreateRuleset, useEntities, useRulesets } from '../api/hooks'
import { ErrorBar, FormDialog, slugify } from '../components/forms'
import { Page } from '../components/Shell'
import { useI18n } from '../i18n'

function NewEntity({ ws }: { ws: string }) {
  const create = useCreateEntity(ws)
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const { t } = useI18n()
  return (
    <FormDialog
      title={t('workspace.newEntity')}
      submitLabel={t('common.create')}
      canSubmit={Boolean(name && key)}
      onSubmit={async () => {
        await create.mutateAsync({ key, name })
        navigate(`/w/${ws}/entities/${key}`)
      }}
      trigger={<Button icon={<Add20Regular />}>{t('workspace.newEntity')}</Button>}
    >
      <Field label={t('common.name')} required hint={t('workspace.entityNameHint')}>
        <Input
          value={name}
          onChange={(_, d) => {
            setName(d.value)
            setKey(d.value.replace(/[^A-Za-z0-9]+/g, ''))
          }}
        />
      </Field>
      <Field label={t('common.key')} required hint={t('workspace.entityKeyHint')}>
        <Input value={key} onChange={(_, d) => setKey(d.value)} />
      </Field>
    </FormDialog>
  )
}

function NewRuleset({ ws }: { ws: string }) {
  const create = useCreateRuleset(ws)
  const entities = useEntities(ws)
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const [entity, setEntity] = useState('')
  const { t } = useI18n()
  return (
    <FormDialog
      title={t('workspace.newRuleset')}
      submitLabel={t('common.create')}
      canSubmit={Boolean(name && key && entity)}
      onSubmit={async () => {
        await create.mutateAsync({ key, name, entity })
        navigate(`/w/${ws}/rulesets/${key}`)
      }}
      trigger={
        <Button appearance="primary" icon={<Add20Regular />}>
          {t('workspace.newRuleset')}
        </Button>
      }
    >
      <Field label={t('common.name')} required hint={t('workspace.rulesetNameHint')}>
        <Input
          value={name}
          onChange={(_, d) => {
            setName(d.value)
            setKey(slugify(d.value))
          }}
        />
      </Field>
      <Field label={t('common.key')} required hint={t('workspace.rulesetKeyHint')}>
        <Input value={key} onChange={(_, d) => setKey(d.value)} />
      </Field>
      <Field label={t('workspace.entity')} required hint={t('workspace.entityHint')}>
        <Dropdown
          placeholder={t('workspace.chooseEntity')}
          value={entity}
          selectedOptions={entity ? [entity] : []}
          onOptionSelect={(_, d) => setEntity(d.optionValue ?? '')}
        >
          {entities.data?.map((e) => (
            <Option key={e.key} value={e.key}>
              {e.key}
            </Option>
          ))}
        </Dropdown>
      </Field>
    </FormDialog>
  )
}

function ImportButton({ ws }: { ws: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<unknown>(null)
  const { t } = useI18n()
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="application/json,.json"
        hidden
        aria-label={t('workspace.importFile')}
        onChange={async (e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          setError(null)
          try {
            const result = await importBundle(ws, JSON.parse(await file.text()) as unknown)
            await Promise.all([
              qc.invalidateQueries({ queryKey: keys.rulesets(ws) }),
              qc.invalidateQueries({ queryKey: keys.entities(ws) }),
              qc.invalidateQueries({ queryKey: keys.draft(ws, result.ruleset) }),
            ])
            navigate(`/w/${ws}/rulesets/${result.ruleset}`)
          } catch (err) {
            setError(err instanceof SyntaxError ? new Error(t('workspace.importInvalid')) : err)
          }
        }}
      />
      <Button icon={<ArrowUpload20Regular />} onClick={() => input.current?.click()}>
        {t('workspace.import')}
      </Button>
      {error !== null && <ErrorBar error={error} />}
    </>
  )
}

export function WorkspacePage() {
  const ws = useParams().ws as string
  const entities = useEntities(ws)
  const rulesets = useRulesets(ws)
  const navigate = useNavigate()
  const { t } = useI18n()

  return (
    <Page
      title={t('workspace.title', { ws })}
      actions={
        <>
          <ImportButton ws={ws} />
          <NewEntity ws={ws} />
          <NewRuleset ws={ws} />
        </>
      }
    >
      <section className="section">
        <Text as="h2" size={500} weight="semibold">
          {t('workspace.rulesets')}
        </Text>
        {rulesets.isLoading && <Spinner size="tiny" />}
        <ErrorBar error={rulesets.error} />
        {rulesets.data?.length === 0 && <Text>{t('workspace.noRulesets')}</Text>}
        <div className="card-grid">
          {rulesets.data?.map((r) => (
            <Card key={r.key} className="clickable" onClick={() => navigate(`/w/${ws}/rulesets/${r.key}`)}>
              <CardHeader
                image={<Flowchart20Regular />}
                header={<Text weight="semibold">{r.name}</Text>}
                description={r.key}
              />
            </Card>
          ))}
        </div>
      </section>
      <section className="section">
        <Text as="h2" size={500} weight="semibold">
          {t('workspace.entities')}
        </Text>
        {entities.isLoading && <Spinner size="tiny" />}
        <ErrorBar error={entities.error} />
        {entities.data?.length === 0 && <Text>{t('workspace.noEntities')}</Text>}
        <div className="card-grid">
          {entities.data?.map((e) => (
            <Card key={e.key} className="clickable" onClick={() => navigate(`/w/${ws}/entities/${e.key}`)}>
              <CardHeader
                image={<Database20Regular />}
                header={<Text weight="semibold">{e.name}</Text>}
                description={e.key}
              />
            </Card>
          ))}
        </div>
      </section>
    </Page>
  )
}
