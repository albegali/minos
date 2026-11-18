import {
  Button,
  Card,
  CardHeader,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Dropdown,
  Field,
  Input,
  Option,
  Spinner,
  Text,
} from '@fluentui/react-components'
import {
  Add20Regular,
  ArrowUpload20Regular,
  Database20Regular,
  Flowchart20Regular,
  People20Regular,
} from '@fluentui/react-icons'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import {
  importBundle,
  keys,
  roleAllows,
  useCreateEntity,
  useCreateRuleset,
  useEntities,
  useMembers,
  useRulesets,
  useSetWorkspaceRole,
  useWorkspaceMembers,
  useWorkspaceRole,
} from '../api/hooks'
import type { WorkspaceRole } from '../api/types'
import { useAuth } from '../auth/store'
import { ErrorBar, FormDialog, slugify } from '../components/forms'
import { Page } from '../components/Shell'
import { useI18n } from '../i18n'
import { RolePicker, WORKSPACE_ROLES } from './MembersPage'
import { RoleLabel } from './OrganizationsPage'

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
  const rulesets = useRulesets(ws)
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
            const bundle = JSON.parse(await file.text()) as {
              ruleset?: { key?: string }
              tests?: unknown[]
            }
            const key = bundle.ruleset?.key
            // An existing rule set's draft is overwritten and its tests of the same name are
            // replaced: say so before doing it.
            if (
              key &&
              rulesets.data?.some((r) => r.key === key) &&
              !window.confirm(t('workspace.importOverwrite', { ruleset: key, count: bundle.tests?.length ?? 0 }))
            ) {
              return
            }
            const result = await importBundle(ws, bundle)
            await Promise.all([
              qc.invalidateQueries({ queryKey: keys.rulesets(ws) }),
              qc.invalidateQueries({ queryKey: keys.entities(ws) }),
              qc.invalidateQueries({ queryKey: keys.draft(ws, result.ruleset) }),
            ])
            if (result.dependencies.length > 0) {
              // Sub rule sets the bundle pins: the draft will not compile until they exist here.
              window.alert(
                t('workspace.importDependencies', {
                  list: result.dependencies.map((d) => `${d.ruleset}@${d.version}`).join(', '),
                }),
              )
            }
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

/**
 * Who can open the workspace: the organization's owners and admins (always admins here) and
 * the members with a role of their own, which workspace admins give and take away.
 */
function AccessDialog({ ws, canManage }: { ws: string; canManage: boolean }) {
  const org = useAuth((s) => s.session?.organization?.slug)
  const [open, setOpen] = useState(false)
  const access = useWorkspaceMembers(ws)
  const members = useMembers(open ? org : undefined)
  const setRole = useSetWorkspaceRole(ws)
  const { t } = useI18n()
  const roleOf = new Map(access.data?.map((m) => [m.id, m]))
  const people = members.data ?? access.data?.map((m) => ({ ...m, role: m.inherited ? 'admin' : 'member' })) ?? []
  return (
    <Dialog open={open} onOpenChange={(_, d) => setOpen(d.open)}>
      <DialogTrigger disableButtonEnhancement>
        <Button icon={<People20Regular />}>{t('workspace.access')}</Button>
      </DialogTrigger>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{t('workspace.accessTitle', { ws })}</DialogTitle>
          <DialogContent className="stack">
            <Text size={200}>{t('workspace.accessIntro')}</Text>
            {(access.isLoading || members.isLoading) && <Spinner size="tiny" />}
            <ErrorBar error={access.error ?? members.error ?? setRole.error} />
            {people.map((p) => {
              const entry = roleOf.get(p.id)
              const inherited = p.role === 'owner' || p.role === 'admin'
              return (
                <div key={p.id} className="row">
                  <div className="grow">
                    <Text weight="semibold">{p.name}</Text> <Text size={200}>{p.email}</Text>
                  </div>
                  {inherited || !canManage ? (
                    <Text>
                      {entry ? <RoleLabel role={entry.role} /> : t('members.noRole')}
                      {inherited && ` (${t('workspace.inherited')})`}
                    </Text>
                  ) : (
                    <RolePicker<WorkspaceRole>
                      label={p.name}
                      value={entry?.role ?? null}
                      roles={WORKSPACE_ROLES}
                      allowNone
                      onChange={(role) => setRole.mutate({ id: p.id, role })}
                    />
                  )}
                </div>
              )
            })}
          </DialogContent>
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="primary">{t('common.close')}</Button>
            </DialogTrigger>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  )
}

export function WorkspacePage() {
  const ws = useParams().ws as string
  const entities = useEntities(ws)
  const rulesets = useRulesets(ws)
  const navigate = useNavigate()
  const role = useWorkspaceRole(ws)
  const signedIn = useAuth((s) => s.session !== null)
  const { t } = useI18n()
  const canWrite = roleAllows(role, 'author')

  return (
    <Page
      title={t('workspace.title', { ws })}
      actions={
        <>
          {signedIn && <AccessDialog ws={ws} canManage={role === 'admin'} />}
          {canWrite && (
            <>
              <ImportButton ws={ws} />
              <NewEntity ws={ws} />
              <NewRuleset ws={ws} />
            </>
          )}
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
