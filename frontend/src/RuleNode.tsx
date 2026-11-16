import { Handle, type NodeProps, Position } from '@xyflow/react'

import type { RuleFlowNode } from './rgd'

const TYPE_LABEL: Record<string, string> = {
  start: 'Start',
  condition: 'Condizione',
  group: 'Gruppo',
  set: 'Calcolo',
  switch: 'Switch',
  feedback: 'Messaggio',
  decision_table: 'Tabella decisionale',
  subruleset: 'Rule set annidato',
  end: 'Fine',
}

export function RuleNode({ data, selected }: NodeProps<RuleFlowNode>) {
  const { rgd, ports, status } = data
  const subtitle =
    rgd.type === 'group'
      ? rgd.operator?.toUpperCase()
      : rgd.type === 'end'
        ? rgd.outcome
        : undefined

  return (
    <div className={`rule-node type-${rgd.type} status-${status}${selected ? ' selected' : ''}`}>
      {rgd.type !== 'start' && <Handle type="target" position={Position.Left} />}
      <div className="rule-node-type">
        {TYPE_LABEL[rgd.type] ?? rgd.type}
        {subtitle && <span className="rule-node-sub"> · {subtitle}</span>}
      </div>
      <div className="rule-node-label">{rgd.label ?? rgd.id}</div>
      <div className="rule-node-ports">
        {ports.map((port, i) => (
          <div key={port} className={`rule-node-port port-${port}`}>
            {port !== 'next' && <span>{port}</span>}
            <Handle
              type="source"
              id={port}
              position={Position.Right}
              style={{ top: `${((i + 1) / (ports.length + 1)) * 100}%` }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
