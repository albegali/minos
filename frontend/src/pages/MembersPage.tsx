import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
} from '@fluentui/react-components'
import { Copy20Regular, Delete20Regular, PersonAdd20Regular } from '@fluentui/react-icons'
import { useState } from 'react'
import { Navigate } from 'react-router'

import { useInvitations, useInvite, useMembers, useRemoveMember, useRevokeInvitation, useSetMemberRole, useWorkspaces } from '../api/hooks'
import type { Invitation, OrgRole, WorkspaceRole } from '../api/types'
import { useAuth } from '../auth/store'
import { ErrorBar, FormDialog } from '../components/forms'
import { Page } from '../components/Shell'
import { useI18n } from '../i18n'
import { RoleLabel } from './OrganizationsPage'

const ORG_ROLES: OrgRole[] = ['member', 'admin', 'owner']
export const WORKSPACE_ROLES: WorkspaceRole[] = ['viewer', 'author', 'publisher', 'admin']

export function RolePicker<R extends string>({
  value,
  roles,
  onChange,
  disabled,
  allowNone,
  label,
}: {
  value: R | null
  roles: R[]
  onChange: (role: R | null) => void
  disabled?: boolean
  allowNone?: boolean
  label: string
}) {
  const { t } = useI18n()
  const text = (r: string) => (r === '' ? t('members.noRole') : t(`roles.${r}` as 'roles.owner'))
  return (
    <Dropdown
      // inline: Fluent's own min-width would win over a stylesheet class
      style={{ minWidth: 0, width: '100%', maxWidth: 200 }}
      aria-label={label}
      disabled={disabled}
      value={text(value ?? '')}
      selectedOptions={[value ?? '']}
      onOptionSelect={(_, d) => onChange((d.optionValue || null) as R | null)}
    >
      {allowNone && <Option value="">{text('')}</Option>}
      {roles.map((r) => (
        <Option key={r} value={r}>
          {text(r)}
        </Option>
      ))}
    </Dropdown>
  )
}

function InviteDialog({ org, myRole }: { org: string; myRole: OrgRole }) {
  const invite = useInvite(org)
  const workspaces = useWorkspaces()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<OrgRole>('member')
  const [grants, setGrants] = useState<Record<string, WorkspaceRole>>({})
  const [created, setCreated] = useState<Invitation | null>(null)
  const [copied, setCopied] = useState(false)
  const { t } = useI18n()
  const roles = myRole === 'owner' ? ORG_ROLES : ORG_ROLES.filter((r) => r !== 'owner')

  return (
    <>
      <FormDialog
        title={t('members.invite')}
        submitLabel={t('members.createInvite')}
        canSubmit={Boolean(email.trim())}
        onSubmit={async () => {
          const inv = await invite.mutateAsync({
            email: email.trim(),
            role,
            workspaces: Object.entries(grants).map(([workspace, r]) => ({ workspace, role: r })),
          })
          setCreated(inv)
          setCopied(false)
          setEmail('')
          setGrants({})
          setRole('member')
        }}
        trigger={<Button icon={<PersonAdd20Regular />}>{t('members.invite')}</Button>}
      >
        <Field label={t('login.email')} required>
          <Input type="email" value={email} onChange={(_, d) => setEmail(d.value)} />
        </Field>
        <Field label={t('members.orgRole')} hint={t('members.orgRoleHint')}>
          <RolePicker label={t('members.orgRole')} value={role} roles={roles} onChange={(r) => setRole(r ?? 'member')} />
        </Field>
        {role === 'member' && (workspaces.data?.length ?? 0) > 0 && (
          <Field label={t('members.workspaceRoles')} hint={t('members.workspaceRolesHint')}>
            <div className="stack">
              {workspaces.data?.map((w) => (
                <div key={w.slug} className="row">
                  <Text className="grow">{w.name}</Text>
                  <RolePicker
                    label={w.name}
                    value={grants[w.slug] ?? null}
                    roles={WORKSPACE_ROLES}
                    allowNone
                    onChange={(r) =>
                      setGrants((g) => {
                        const next = Object.fromEntries(Object.entries(g).filter(([k]) => k !== w.slug))
                        return r ? { ...next, [w.slug]: r } : next
                      })
                    }
                  />
                </div>
              ))}
            </div>
          </Field>
        )}
      </FormDialog>
      <Dialog open={created !== null} onOpenChange={(_, d) => !d.open && setCreated(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('members.linkTitle')}</DialogTitle>
            <DialogContent className="stack">
              <Text>{t('members.linkIntro', { email: created?.email ?? '' })}</Text>
              <Input readOnly value={created?.url ?? ''} aria-label={t('members.linkTitle')} />
              {copied && (
                <MessageBar intent="success">
                  <MessageBarBody>{t('members.copied')}</MessageBarBody>
                </MessageBar>
              )}
            </DialogContent>
            <DialogActions>
              <Button
                icon={<Copy20Regular />}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(created?.url ?? '')
                    setCopied(true)
                  } catch {
                    // no clipboard access: the link stays selectable in the field
                  }
                }}
              >
                {t('members.copy')}
              </Button>
              <Button appearance="primary" onClick={() => setCreated(null)}>
                {t('common.close')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  )
}

/** Members and invitations of the organization of the session. */
export function MembersPage() {
  const session = useAuth((s) => s.session)
  const org = session?.organization
  const members = useMembers(org?.slug)
  const myRole = org?.role ?? 'member'
  const manager = myRole === 'owner' || myRole === 'admin'
  const invitations = useInvitations(org?.slug, manager)
  const setRole = useSetMemberRole(org?.slug ?? '')
  const remove = useRemoveMember(org?.slug ?? '')
  const revoke = useRevokeInvitation(org?.slug ?? '')
  const { t } = useI18n()

  if (!session) return <Navigate to="/w" replace />
  if (!org) return <Navigate to="/organizations" replace />

  const canManage = (role: OrgRole) => manager && (myRole === 'owner' || role !== 'owner')
  // the server refuses to leave an organization without owners: do not offer it
  const lastOwner = (members.data?.filter((m) => m.role === 'owner').length ?? 0) <= 1

  return (
    <Page title={t('members.title', { org: org.name })} actions={manager && <InviteDialog org={org.slug} myRole={myRole} />}>
      {members.isLoading && <Spinner size="tiny" />}
      <ErrorBar error={members.error ?? setRole.error ?? remove.error ?? revoke.error} />
      <Table aria-label={t('members.members')}>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{t('common.name')}</TableHeaderCell>
            <TableHeaderCell>{t('members.emails')}</TableHeaderCell>
            <TableHeaderCell>{t('members.orgRole')}</TableHeaderCell>
            <TableHeaderCell>{t('members.workspaceRoles')}</TableHeaderCell>
            <TableHeaderCell />
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.data?.map((m) => {
            const self = m.id === session.user.id
            return (
              <TableRow key={m.id}>
                <TableCell>{m.name}</TableCell>
                <TableCell>{m.emails.join(', ')}</TableCell>
                <TableCell>
                  {canManage(m.role) ? (
                    <RolePicker
                      label={t('members.orgRole')}
                      value={m.role}
                      roles={myRole === 'owner' ? ORG_ROLES : ORG_ROLES.filter((r) => r !== 'owner')}
                      onChange={(r) => r && setRole.mutate({ id: m.id, role: r })}
                    />
                  ) : (
                    <RoleLabel role={m.role} />
                  )}
                </TableCell>
                <TableCell>
                  {m.role === 'member'
                    ? m.workspaces.map((w) => `${w.workspace}: ${t(`roles.${w.role}` as 'roles.owner')}`).join(', ') || '—'
                    : t('members.allWorkspaces')}
                </TableCell>
                <TableCell>
                  {(canManage(m.role) || self) && !(m.role === 'owner' && lastOwner) && (
                    <Button
                      appearance="subtle"
                      icon={<Delete20Regular />}
                      aria-label={self ? t('members.leave') : t('common.remove')}
                      onClick={() => {
                        const question = self ? t('members.leaveConfirm', { org: org.name }) : t('members.removeConfirm', { name: m.name })
                        if (window.confirm(question)) remove.mutate(m.id)
                      }}
                    >
                      {self ? t('members.leave') : undefined}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      {manager && (
        <section className="section">
          <Text as="h2" size={500} weight="semibold">
            {t('members.pending')}
          </Text>
          {invitations.data?.length === 0 && <Text>{t('members.noPending')}</Text>}
          {(invitations.data?.length ?? 0) > 0 && (
            <Table aria-label={t('members.pending')}>
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>{t('login.email')}</TableHeaderCell>
                  <TableHeaderCell>{t('members.orgRole')}</TableHeaderCell>
                  <TableHeaderCell>{t('members.invitedBy')}</TableHeaderCell>
                  <TableHeaderCell>{t('members.expires')}</TableHeaderCell>
                  <TableHeaderCell />
                </TableRow>
              </TableHeader>
              <TableBody>
                {invitations.data?.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell>{i.email}</TableCell>
                    <TableCell>
                      <RoleLabel role={i.role} />
                    </TableCell>
                    <TableCell>{i.invitedBy}</TableCell>
                    <TableCell>{new Date(i.expiresAt).toLocaleDateString()}</TableCell>
                    <TableCell>
                      <Button appearance="subtle" onClick={() => revoke.mutate(i.id)}>
                        {t('members.revoke')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </section>
      )}
    </Page>
  )
}
