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

function NewEntity({ ws }: { ws: string }) {
  const create = useCreateEntity(ws)
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  return (
    <FormDialog
      title="Nuova entità"
      submitLabel="Crea"
      canSubmit={Boolean(name && key)}
      onSubmit={async () => {
        await create.mutateAsync({ key, name })
        navigate(`/w/${ws}/entities/${key}`)
      }}
      trigger={<Button icon={<Add20Regular />}>Nuova entità</Button>}
    >
      <Field label="Nome" required hint="Es. Piano di studi">
        <Input
          value={name}
          onChange={(_, d) => {
            setName(d.value)
            setKey(d.value.replace(/[^A-Za-z0-9]+/g, ''))
          }}
        />
      </Field>
      <Field label="Chiave" required hint="Es. StudyPlan">
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
  return (
    <FormDialog
      title="Nuovo rule set"
      submitLabel="Crea"
      canSubmit={Boolean(name && key && entity)}
      onSubmit={async () => {
        await create.mutateAsync({ key, name, entity })
        navigate(`/w/${ws}/rulesets/${key}`)
      }}
      trigger={
        <Button appearance="primary" icon={<Add20Regular />}>
          Nuovo rule set
        </Button>
      }
    >
      <Field label="Nome" required hint="Es. Piano di studi Executive MBA">
        <Input
          value={name}
          onChange={(_, d) => {
            setName(d.value)
            setKey(slugify(d.value))
          }}
        />
      </Field>
      <Field label="Chiave" required hint="Usata nell'URL di esecuzione">
        <Input value={key} onChange={(_, d) => setKey(d.value)} />
      </Field>
      <Field label="Entità" required hint="Lo schema dell'entità guida l'editor">
        <Dropdown
          placeholder="Scegli un'entità"
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
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="application/json,.json"
        hidden
        aria-label="File da importare"
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
            setError(err instanceof SyntaxError ? new Error('Il file non è un JSON valido') : err)
          }
        }}
      />
      <Button icon={<ArrowUpload20Regular />} onClick={() => input.current?.click()}>
        Importa
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

  return (
    <Page
      title={`Workspace ${ws}`}
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
          Rule set
        </Text>
        {rulesets.isLoading && <Spinner size="tiny" />}
        <ErrorBar error={rulesets.error} />
        {rulesets.data?.length === 0 && <Text>Nessun rule set: creane uno dopo aver definito un'entità.</Text>}
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
          Entità e schemi
        </Text>
        {entities.isLoading && <Spinner size="tiny" />}
        <ErrorBar error={entities.error} />
        {entities.data?.length === 0 && <Text>Nessuna entità.</Text>}
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
