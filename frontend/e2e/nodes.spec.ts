// A decision table built only from the Studio: columns, cells in the short text syntax,
// first-hit policy, result reused by the end node, checked by a simulation.

import { expect, type Page, test } from '@playwright/test'

const API = 'http://127.0.0.1:8000/v1'

async function pick(page: Page, name: string, option: string, type?: string) {
  const box = page.locator('.editor-panel').getByRole('combobox', { name, exact: true }).first()
  await box.click()
  if (type) await box.fill(type)
  await page.getByRole('option', { name: option, exact: true }).first().click()
}

async function wire(page: Page, from: string, port: string, to: string) {
  const src = page.locator(`.react-flow__node[data-id="${from}"] .react-flow__handle.source[data-handleid="${port}"]`)
  const dst = page.locator(`.react-flow__node[data-id="${to}"] .react-flow__handle.target`)
  const a = await src.boundingBox()
  const b = await dst.boundingBox()
  if (!a || !b) throw new Error('handles not visible')
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 })
  await page.mouse.up()
}

test('a decision table is built and simulated from the Studio', async ({ page, request }) => {
  const ws = `${API}/workspaces/aurora`
  await request.post(`${ws}/entities`, { data: { key: 'Order', name: 'Ordine' } })
  await request.post(`${ws}/entities/Order/schemas`, {
    data: { samples: [{ country: 'IT', total: 120 }, { country: 'FR', total: 20 }] },
  })
  await request.post(`${ws}/rulesets`, { data: { key: 'shipping', name: 'Spedizione', entity: 'Order' } })

  await page.goto('/w/aurora/rulesets/shipping')
  await page.getByRole('button', { name: /^Tabella decisionale/ }).click()
  const node = page.locator('.react-flow__node[data-id="decision_table1"]')
  await expect(node).toBeVisible()
  const panel = page.locator('.editor-panel')

  // two input columns bound to fields, one output column
  await panel.getByRole('button', { name: 'Scegli il valore' }).click()
  await pick(page, 'Campo', '$.input.country', 'country')
  await panel.getByRole('button', { name: 'Input', exact: true }).click()
  await pick(page, 'Campo', '$.input.total', 'total')
  await panel.getByLabel('Nome output 1').fill('cost')
  await panel.getByLabel('Nome output 1').blur()
  await panel.getByLabel('Salva il risultato in').fill('shipping')

  // rows: IT and >= 100 -> free; IT -> 5; anything else -> 15
  await panel.getByLabel('Riga 1, input', { exact: true }).fill('IT')
  await panel.getByLabel('Riga 1, input2').fill('>= 100')
  await panel.getByLabel('Riga 1, cost').fill('0')
  await panel.getByRole('button', { name: 'Riga', exact: true }).click()
  await panel.getByLabel('Riga 2, input', { exact: true }).fill('IT')
  await panel.getByLabel('Riga 2, cost').fill('5')
  await panel.getByRole('button', { name: 'Riga', exact: true }).click()
  await panel.getByLabel('Riga 3, cost').fill('15')
  await panel.getByLabel('Riga 3, cost').blur()
  await expect(node).toContainText('3 righe')

  await wire(page, 'start', 'next', 'decision_table1')
  await wire(page, 'decision_table1', 'pass', 'end')
  await page.locator('.react-flow__node[data-id="end"]').click()
  await panel.getByRole('button', { name: 'Valore in output' }).click()
  await pick(page, 'Tipo di espressione', 'Campo')
  await pick(page, 'Campo', '$.vars.shipping', 'shipping')

  await page.getByRole('button', { name: 'Valida' }).click()
  await expect(page.locator('.editor-toolbar').getByText('Valido', { exact: true })).toBeVisible()

  for (const [input, cost] of [
    [{ country: 'IT', total: 150 }, 0],
    [{ country: 'IT', total: 30 }, 5],
    [{ country: 'FR', total: 300 }, 15],
  ] as const) {
    await page.getByRole('tab', { name: 'Simulazione' }).click()
    await panel.getByLabel('Oggetto in input').fill(JSON.stringify(input))
    await panel.getByRole('button', { name: 'Simula il draft' }).click()
    await expect(panel.locator('pre').last()).toContainText(`"cost": ${cost}`)
  }
})
