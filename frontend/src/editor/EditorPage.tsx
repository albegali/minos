import {
  Badge,
  Button,
  MessageBar,
  MessageBarBody,
  Spinner,
  Tab,
  TabList,
  Text,
  Tooltip,
} from '@fluentui/react-components'
import {
  ArrowDownload20Regular,
  ArrowRedo20Regular,
  ArrowUndo20Regular,
  Beaker20Regular,
  Checkmark20Regular,
  Cube20Regular,
  Dismiss20Regular,
  History20Regular,
  Organization20Regular,
  PanelRightContract20Regular,
  PanelRightExpand20Regular,
  Play20Regular,
  Save20Regular,
  Settings20Regular,
} from '@fluentui/react-icons'
import { useQueryClient } from '@tanstack/react-query'
import { ReactFlowProvider } from '@xyflow/react'
import { type ReactElement, useCallback, useEffect, useMemo, useState } from 'react'
import { useBlocker, useParams } from 'react-router'

import { ApiError, errorMessage } from '../api/client'
import { type Key, useI18n } from '../i18n'
import { downloadJson, exportBundle, keys, saveDraft, useCatalog, useDraft, useRuleset, useSchema, useSchemas, validateDraft } from '../api/hooks'
import { Canvas, Palette } from './Canvas'
import { type FieldScope, ScopeContext } from './FieldPicker'
import { addNode, defaultNode, frozenPositions, issueNode, newNodeId, variableNames } from './graph'
import { autoLayout } from './layout'
import { NodePanel } from './NodePanel'
import { IssueList, NodeIO, SettingsPanel, SimulatePanel, TestsPanel, VersionsPanel } from './panels'
import { listFields } from './schemaPaths'
import { type PanelTab, useEditor } from './store'

const PANEL_TABS: { value: PanelTab; label: Key; icon: ReactElement }[] = [
  { value: 'node', label: 'editor.tabNode', icon: <Cube20Regular /> },
  { value: 'simulate', label: 'editor.tabSimulate', icon: <Play20Regular /> },
  { value: 'tests', label: 'editor.tabTests', icon: <Beaker20Regular /> },
  { value: 'versions', label: 'editor.tabVersions', icon: <History20Regular /> },
  { value: 'settings', label: 'editor.tabSettings', icon: <Settings20Regular /> },
]

/** Rendered node sizes, so the layout leaves room for large nodes. */
function measuredSizes(): Record<string, { width: number; height: number }> {
  const out: Record<string, { width: number; height: number }> = {}
  document.querySelectorAll<HTMLElement>('.react-flow__node[data-id]').forEach((el) => {
    const id = el.dataset.id
    if (id) out[id] = { width: el.offsetWidth, height: el.offsetHeight }
  })
  return out
}

export function EditorPage() {
  const { ws, rs } = useParams() as { ws: string; rs: string }
  const draft = useDraft(ws, rs)
  const info = useRuleset(ws, rs)
  const catalog = useCatalog()
  const qc = useQueryClient()
  const { t } = useI18n()

  const graph = useEditor((s) => s.graph)
  const load = useEditor((s) => s.load)
  const dirty = useEditor((s) => s.dirty)
  const lockVersion = useEditor((s) => s.lockVersion)
  const schemaVersion = useEditor((s) => s.schemaVersion)
  const selected = useEditor((s) => s.selected)
  const tab = useEditor((s) => s.tab)
  const issues = useEditor((s) => s.issues)
  const warnings = useEditor((s) => s.warnings)
  const validated = useEditor((s) => s.validated)
  const change = useEditor((s) => s.change)
  const select = useEditor((s) => s.select)
  const setTab = useEditor((s) => s.setTab)
  const panelOpen = useEditor((s) => s.panelOpen)
  const setPanelOpen = useEditor((s) => s.setPanelOpen)
  const canUndo = useEditor((s) => s.past.length > 0)
  const canRedo = useEditor((s) => s.future.length > 0)

  const entity = info.data?.entity ?? undefined
  const schemas = useSchemas(ws, entity ?? '')
  const schema = useSchema(ws, entity ?? '', schemaVersion ?? schemas.data?.[0]?.version)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (draft.data) load(draft.data)
  }, [draft.data, load])

  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname)
  useEffect(() => {
    if (blocker.state === 'blocked') {
      if (window.confirm(t('editor.unsavedConfirm'))) blocker.proceed()
      else blocker.reset()
    }
  }, [blocker, t])
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (useEditor.getState().dirty) e.preventDefault()
    }
    window.addEventListener('beforeunload', onUnload)
    return () => window.removeEventListener('beforeunload', onUnload)
  }, [])

  const validate = useCallback(async () => {
    const v = await validateDraft(ws, rs)
    useEditor.getState().setValidation(v.issues, v.warnings)
    return v
  }, [ws, rs])

  const save = useCallback(async (): Promise<boolean> => {
    const s = useEditor.getState()
    if (!s.graph) return false
    if (!s.dirty) return true
    setSaveError(null)
    try {
      const lock = await saveDraft(ws, rs, s.graph, s.lockVersion, s.schemaVersion)
      s.saved(lock)
      await validate()
      return true
    } catch (e) {
      setSaveError(e)
      return false
    }
  }, [ws, rs, validate])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      const key = e.key.toLowerCase()
      if (key === 's') {
        e.preventDefault()
        void save()
        return
      }
      // Inside a text field the browser's own undo applies to the text.
      const target = e.target as HTMLElement | null
      if (target?.closest('input, textarea, [contenteditable="true"]')) return
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault()
        useEditor.getState().undo()
      } else if (key === 'y' || (key === 'z' && e.shiftKey)) {
        e.preventDefault()
        useEditor.getState().redo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [save])

  const scope: FieldScope | null = useMemo(() => {
    if (!catalog.data || !graph) return null
    const s = schema.data?.schema
    return {
      catalog: catalog.data,
      schema: s,
      input: listFields(s),
      vars: variableNames(graph),
      nodes: graph.nodes.map((n) => n.id),
    }
  }, [catalog.data, graph, schema.data])

  if (draft.isLoading || catalog.isLoading || !graph) {
    return draft.error || catalog.error ? (
      <MessageBar intent="error">
        <MessageBarBody>{errorMessage(draft.error ?? catalog.error)}</MessageBarBody>
      </MessageBar>
    ) : (
      <Spinner label={t('editor.loading')} />
    )
  }
  if (!catalog.data || !scope) return null

  const node = graph.nodes.find((n) => n.id === selected)
  const manifest = catalog.data.nodeTypes.find((m) => m.type === node?.type)
  const conflict = saveError instanceof ApiError && saveError.status === 412

  function addAtCentre(type: string) {
    const g = useEditor.getState().graph
    if (!g) return
    const id = newNodeId(g, type)
    const positions = Object.values(frozenPositions(g))
    const x = (positions.length ? Math.max(...positions.map((p) => p[0])) : 0) + 280
    const y = positions.length ? Math.min(...positions.map((p) => p[1])) : 0
    change((current) => addNode(current, defaultNode(type, id), [x, y]))
    select(id)
  }

  return (
    <ScopeContext.Provider value={scope}>
      <div className="editor">
        <div className="editor-toolbar">
          <div className="inline editor-title">
            <Text weight="bold" size={500}>
              {info.data?.name ?? rs}
            </Text>
            {info.data?.latestVersion && <Badge appearance="tint">{t('editor.latest', { version: info.data.latestVersion })}</Badge>}
            {Object.entries(info.data?.aliases ?? {}).map(([env, v]) => (
              <Badge key={env} appearance="outline">
                {env}: {v}
              </Badge>
            ))}
          </div>
          <div className="inline">
            <span className={`save-state${dirty ? ' dirty' : ''}`} aria-live="polite">
              {dirty ? t('editor.unsaved') : t('editor.saved', { rev: lockVersion })}
            </span>
            {validated && (
              <Badge color={issues.length ? 'danger' : 'success'} appearance="filled">
                {issues.length ? t('editor.problems', { count: issues.length }) : t('editor.valid')}
              </Badge>
            )}
            <Tooltip content={t('editor.undo')} relationship="label">
              <Button
                appearance="subtle"
                icon={<ArrowUndo20Regular />}
                disabled={!canUndo}
                onClick={() => useEditor.getState().undo()}
              />
            </Tooltip>
            <Tooltip content={t('editor.redo')} relationship="label">
              <Button
                appearance="subtle"
                icon={<ArrowRedo20Regular />}
                disabled={!canRedo}
                onClick={() => useEditor.getState().redo()}
              />
            </Tooltip>
            <Tooltip content={t('editor.layoutHint')} relationship="description">
              <Button
                appearance="subtle"
                icon={<Organization20Regular />}
                onClick={() =>
                  change((g) => ({ ...g, ui: { ...g.ui, positions: autoLayout(g, measuredSizes()) } }), {
                    coalesce: false,
                  })
                }
              >
                {t('editor.layout')}
              </Button>
            </Tooltip>
            <Tooltip content="Ctrl+S" relationship="description">
              <Button icon={<Save20Regular />} disabled={!dirty || busy} onClick={() => void save()}>
                {t('editor.save')}
              </Button>
            </Tooltip>
            <Button
              icon={<Checkmark20Regular />}
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                try {
                  if (await save()) await validate()
                } finally {
                  setBusy(false)
                }
              }}
            >
              {t('editor.validate')}
            </Button>
            <Button icon={<Play20Regular />} onClick={() => setTab('simulate')}>
              {t('editor.simulate')}
            </Button>
            <Tooltip content={t('editor.exportHint')} relationship="description">
              <Button
                icon={<ArrowDownload20Regular />}
                onClick={async () => {
                  if (await save()) downloadJson(`${rs}-draft.minos.json`, await exportBundle(ws, rs))
                }}
              >
                {t('editor.export')}
              </Button>
            </Tooltip>
            <Button appearance="primary" onClick={() => setTab('versions')}>
              {t('editor.publish')}
            </Button>
            <span className="toolbar-sep" aria-hidden="true" />
            <Tooltip content={panelOpen ? t('editor.closePanel') : t('editor.openPanel')} relationship="label">
              <Button
                appearance="subtle"
                aria-expanded={panelOpen}
                aria-controls="editor-panel"
                icon={panelOpen ? <PanelRightContract20Regular /> : <PanelRightExpand20Regular />}
                onClick={() => setPanelOpen(!panelOpen)}
              />
            </Tooltip>
          </div>
        </div>

        {saveError !== null && (
          <MessageBar intent="error">
            <MessageBarBody>
              {conflict
                ? t('editor.conflict')
                : errorMessage(saveError)}
            </MessageBarBody>
            {conflict && (
              <Button
                onClick={async () => {
                  setSaveError(null)
                  await qc.invalidateQueries({ queryKey: keys.draft(ws, rs) })
                }}
              >
                {t('editor.reload')}
              </Button>
            )}
          </MessageBar>
        )}

        <div className={`editor-body${panelOpen ? '' : ' panel-closed'}`}>
          <Palette catalog={catalog.data} onAdd={addAtCentre} />
          <section className="editor-canvas" aria-label={t('editor.canvas')}>
            <ReactFlowProvider>
              <Canvas graph={graph} catalog={catalog.data} />
            </ReactFlowProvider>
          </section>
          {panelOpen ? (
            <aside className="editor-panel" id="editor-panel">
              <div className="editor-panel-head">
                <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value as PanelTab)} size="small">
                  {PANEL_TABS.map((item) => (
                    <Tab key={item.value} value={item.value}>
                      {t(item.label)}
                    </Tab>
                  ))}
                </TabList>
                <Tooltip content={t('editor.closePanel')} relationship="label">
                  <Button appearance="subtle" size="small" icon={<Dismiss20Regular />} onClick={() => setPanelOpen(false)} />
                </Tooltip>
              </div>
              <div className="editor-panel-body">
                {tab === 'node' &&
                  (node ? (
                    <>
                      <NodePanel key={node.id} node={node} manifest={manifest} />
                      <NodeIO nodeId={node.id} />
                    </>
                  ) : (
                    <div className="empty-hint">
                      <Cube20Regular />
                      <Text>{t('editor.emptyHint')}</Text>
                    </div>
                  ))}
                {tab === 'simulate' && <SimulatePanel ws={ws} rs={rs} ensureSaved={save} />}
                {tab === 'tests' && <TestsPanel ws={ws} rs={rs} ensureSaved={save} />}
                {tab === 'versions' && <VersionsPanel ws={ws} rs={rs} ensureSaved={save} />}
                {tab === 'settings' && <SettingsPanel ws={ws} entity={entity} />}
              </div>
            </aside>
          ) : (
            <nav className="editor-rail" aria-label={t('editor.panels')}>
              {PANEL_TABS.map((item) => (
                <Tooltip key={item.value} content={t(item.label)} relationship="label" positioning="before">
                  <Button
                    appearance="subtle"
                    icon={item.icon}
                    className={item.value === tab ? 'rail-active' : undefined}
                    onClick={() => setTab(item.value)}
                  />
                </Tooltip>
              ))}
            </nav>
          )}
        </div>

        {validated && (issues.length > 0 || warnings.length > 0) && (
          <div className="issues-bar" role="region" aria-label={t('editor.issues')}>
            <IssueList
              issues={issues}
              onSelect={(where) => {
                const id = issueNode(where)
                if (id) select(id)
              }}
            />
            {warnings.map((w) => (
              <Text key={w} size={200} className="muted">
                {w}
              </Text>
            ))}
          </div>
        )}
      </div>
    </ScopeContext.Provider>
  )
}
