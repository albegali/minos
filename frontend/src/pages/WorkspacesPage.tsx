import { Button, Card, CardHeader, Field, Input, Spinner, Text } from '@fluentui/react-components'
import { Add20Regular, Folder20Regular } from '@fluentui/react-icons'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { useCreateWorkspace, useWorkspaces } from '../api/hooks'
import { ErrorBar, FormDialog, slugify } from '../components/forms'
import { Page } from '../components/Shell'

export function WorkspacesPage() {
  const { data, isLoading, error } = useWorkspaces()
  const create = useCreateWorkspace()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')

  return (
    <Page
      title="Workspace"
      actions={
        <FormDialog
          title="Nuovo workspace"
          submitLabel="Crea"
          canSubmit={Boolean(name && slug)}
          onSubmit={async () => {
            await create.mutateAsync({ slug, name })
            navigate(`/w/${slug}`)
          }}
          trigger={<Button icon={<Add20Regular />}>Nuovo workspace</Button>}
        >
          <Field label="Nome" required>
            <Input
              value={name}
              onChange={(_, d) => {
                setName(d.value)
                setSlug(slugify(d.value))
              }}
            />
          </Field>
          <Field label="Identificativo" hint="Usato negli URL delle API. Richiede una chiave admin.">
            <Input value={slug} onChange={(_, d) => setSlug(d.value)} />
          </Field>
        </FormDialog>
      }
    >
      {isLoading && <Spinner label="Caricamento…" />}
      <ErrorBar error={error} />
      {data?.length === 0 && <Text>Nessun workspace. Creane uno per iniziare.</Text>}
      <div className="card-grid">
        {data?.map((w) => (
          <Card key={w.slug} onClick={() => navigate(`/w/${w.slug}`)} className="clickable">
            <CardHeader image={<Folder20Regular />} header={<Text weight="semibold">{w.name}</Text>} description={w.slug} />
          </Card>
        ))}
      </div>
    </Page>
  )
}
