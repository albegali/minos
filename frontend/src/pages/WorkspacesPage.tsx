import { Button, Card, CardHeader, Field, Input, Spinner, Text } from '@fluentui/react-components'
import { Add20Regular, Folder20Regular } from '@fluentui/react-icons'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { useCreateWorkspace, useWorkspaces } from '../api/hooks'
import { useAuth } from '../auth/store'
import { ErrorBar, FormDialog, slugify } from '../components/forms'
import { Page } from '../components/Shell'
import { useI18n } from '../i18n'
import { RoleLabel } from './OrganizationsPage'

export function WorkspacesPage() {
  const { data, isLoading, error } = useWorkspaces()
  const create = useCreateWorkspace()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const session = useAuth((s) => s.session)
  const { t } = useI18n()
  // Signed-in users create workspaces as owners or admins of the organization; with an API
  // key the server decides (admin keys only).
  const orgRole = session?.organization?.role
  const canCreate = !session || orgRole === 'owner' || orgRole === 'admin'

  return (
    <Page
      title={session?.organization ? t('workspaces.titleIn', { org: session.organization.name }) : t('workspaces.title')}
      actions={
        canCreate && (
        <FormDialog
          title={t('workspaces.new')}
          submitLabel={t('common.create')}
          canSubmit={Boolean(name && slug)}
          onSubmit={async () => {
            await create.mutateAsync({ slug, name })
            navigate(`/w/${slug}`)
          }}
          trigger={<Button icon={<Add20Regular />}>{t('workspaces.new')}</Button>}
        >
          <Field label={t('common.name')} required>
            <Input
              value={name}
              onChange={(_, d) => {
                setName(d.value)
                setSlug(slugify(d.value))
              }}
            />
          </Field>
          <Field label={t('workspaces.slug')} hint={t('workspaces.slugHint')}>
            <Input value={slug} onChange={(_, d) => setSlug(d.value)} />
          </Field>
        </FormDialog>
        )
      }
    >
      {isLoading && <Spinner label={t('common.loading')} />}
      <ErrorBar error={error} />
      {data?.length === 0 && <Text>{t('workspaces.empty')}</Text>}
      <div className="card-grid">
        {data?.map((w) => (
          <Card key={w.slug} onClick={() => navigate(`/w/${w.slug}`)} className="clickable">
            <CardHeader
              image={<Folder20Regular />}
              header={<Text weight="semibold">{w.name}</Text>}
              description={
                <Text size={200}>
                  {w.slug}
                  {w.role && (
                    <>
                      {' · '}
                      <RoleLabel role={w.role} />
                    </>
                  )}
                </Text>
              }
            />
          </Card>
        ))}
      </div>
    </Page>
  )
}
