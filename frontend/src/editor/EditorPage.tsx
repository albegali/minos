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
  Checkmark20Regular,
  Organization20Regular,
  Play20Regular,
  Save20Regular,
} from '@fluentui/react-icons'
import { useQueryClient } from '@tanstack/react-query'
import { ReactFlowProvider } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useBlocker, useParams } from 'react-router'

import { ApiError, errorMessage } from '../api/client'
import { downloadJson, exportBundle, keys, saveDraft, useCatalog, useDraft, useRuleset, useSchema, useSchemas, validateDraft } from '../api/hooks'
import { Canvas, Palette } from './Canvas'
import { type FieldScope, ScopeContext } from './FieldPicker'
import { addNode, defaultNode, frozenPositions, issueNode, newNodeId, variableNames } from './graph'
import { autoLayout } from './layout'
import { NodePanel } from './NodePanel'
import { IssueList, NodeIO, SettingsPanel, SimulatePanel, TestsPanel, VersionsPanel } from './panels'
import { listFields } from './schemaPaths'
import { type PanelTab, useEditor } from './store'

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
      if (window.confirm('Ci sono modifiche non salvate. Uscire comunque?')) blocker.proceed()
      else blocker.reset()
    }
  }, [blocker])
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
      <Spinner label="Caricamento del rule set…" />
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
          <div className="inline">
            <Text weight="semibold" size={500}>
              {info.data?.name ?? rs}
            </Text>
            {info.data?.latestVersion && <Badge appearance="tint">ultima {info.data.latestVersion}</Badge>}
            {Object.entries(info.data?.aliases ?? {}).map(([env, v]) => (
              <Badge key={env} appearance="outline">
                {env}: {v}
              </Badge>
            ))}
          </div>
          <div className="inline">
            <Text size={200} className="muted" aria-live="polite">
              {dirty ? 'Modifiche non salvate' : `Salvato (rev. ${lockVersion})`}
            </Text>
            {validated && (
              <Badge color={issues.length ? 'danger' : 'success'} appearance="filled">
                {issues.length ? `${issues.length} problemi` : 'Valido'}
              </Badge>
            )}
            <Tooltip content="Annulla (Ctrl+Z)" relationship="label">
              <Button
                appearance="subtle"
                icon={<ArrowUndo20Regular />}
                disabled={!canUndo}
                onClick={() => useEditor.getState().undo()}
              />
            </Tooltip>
            <Tooltip content="Ripristina (Ctrl+Shift+Z)" relationship="label">
              <Button
                appearance="subtle"
                icon={<ArrowRedo20Regular />}
                disabled={!canRedo}
                onClick={() => useEditor.getState().redo()}
              />
            </Tooltip>
            <Tooltip content="Dispone i nodi da sinistra a destra seguendo i collegamenti" relationship="description">
              <Button
                appearance="subtle"
                icon={<Organization20Regular />}
                onClick={() =>
                  change((g) => ({ ...g, ui: { ...g.ui, positions: autoLayout(g, measuredSizes()) } }), {
                    coalesce: false,
                  })
                }
              >
                Riordina
              </Button>
            </Tooltip>
            <Tooltip content="Ctrl+S" relationship="description">
              <Button icon={<Save20Regular />} disabled={!dirty || busy} onClick={() => void save()}>
                Salva
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
              Valida
            </Button>
            <Button icon={<Play20Regular />} onClick={() => setTab('simulate')}>
              Simula
            </Button>
            <Tooltip content="Scarica il draft con schema e test, da importare altrove" relationship="description">
              <Button
                icon={<ArrowDownload20Regular />}
                onClick={async () => {
                  if (await save()) downloadJson(`${rs}-draft.minos.json`, await exportBundle(ws, rs))
                }}
              >
                Esporta
              </Button>
            </Tooltip>
            <Button appearance="primary" onClick={() => setTab('versions')}>
              Pubblica
            </Button>
          </div>
        </div>

        {saveError !== null && (
          <MessageBar intent="error">
            <MessageBarBody>
              {conflict
                ? 'Il draft è stato modificato da qualcun altro. Ricarica per vedere la versione aggiornata (le tue modifiche andranno perse).'
                : errorMessage(saveError)}
            </MessageBarBody>
            {conflict && (
              <Button
                onClick={async () => {
                  setSaveError(null)
                  await qc.invalidateQueries({ queryKey: keys.draft(ws, rs) })
                }}
              >
                Ricarica
              </Button>
            )}
          </MessageBar>
        )}

        <div className="editor-body">
          <Palette catalog={catalog.data} onAdd={addAtCentre} />
          <section className="editor-canvas" aria-label="Grafo delle regole">
            <ReactFlowProvider>
              <Canvas graph={graph} catalog={catalog.data} />
            </ReactFlowProvider>
          </section>
          <aside className="editor-panel">
            <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value as PanelTab)} size="small">
              <Tab value="node">Nodo</Tab>
              <Tab value="simulate">Simulazione</Tab>
              <Tab value="tests">Test</Tab>
              <Tab value="versions">Versioni</Tab>
              <Tab value="settings">Impostazioni</Tab>
            </TabList>
            <div className="editor-panel-body">
              {tab === 'node' &&
                (node ? (
                  <>
                    <NodePanel key={node.id} node={node} manifest={manifest} />
                    <NodeIO nodeId={node.id} />
                  </>
                ) : (
                  <Text>
                    Trascina un nodo dalla palette sul canvas, collega le uscite agli ingressi e seleziona un nodo per
                    configurarlo.
                  </Text>
                ))}
              {tab === 'simulate' && <SimulatePanel ws={ws} rs={rs} ensureSaved={save} />}
              {tab === 'tests' && <TestsPanel ws={ws} rs={rs} ensureSaved={save} />}
              {tab === 'versions' && <VersionsPanel ws={ws} rs={rs} ensureSaved={save} />}
              {tab === 'settings' && <SettingsPanel ws={ws} entity={entity} />}
            </div>
          </aside>
        </div>

        {validated && (issues.length > 0 || warnings.length > 0) && (
          <div className="issues-bar" role="region" aria-label="Problemi">
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
