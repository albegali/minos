// Version lifecycle from the Studio: compare a version with the draft, schedule a version
// from a date, export the rule set as a file and import it into another workspace.

import { readFileSync } from 'node:fs'

import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8000/v1'

const graph = (minimum: number) => ({
  rgdVersion: '1.0',
  ruleset: 'credit',
  settings: { mode: 'collect_all' },
  constants: { minimum },
  nodes: [
    { id: 'start', type: 'start' },
    {
      id: 'score',
      type: 'condition',
      label: 'Punteggio minimo',
      condition: { op: '>=', left: { ref: '$.input.score' }, right: { ref: '$.vars.minimum' } },
    },
    { id: 'end', type: 'end', outcome: 'valid' },
  ],
  edges: [
    { from: 'start', to: 'score' },
    { from: 'score', to: 'end', on: 'pass' },
  ],
})

test('compare, schedule, export and import', async ({ page, request }) => {
  const ws = `${API}/workspaces/aurora`
  await request.post(`${ws}/entities`, { data: { key: 'Application', name: 'Richiesta' } })
  await request.post(`${ws}/entities/Application/schemas`, { data: { samples: [{ score: 700 }] } })
  await request.post(`${ws}/rulesets`, {
    data: { key: 'credit', name: 'Finanziamento', entity: 'Application', graph: graph(600) },
  })
  await request.post(`${ws}/rulesets/credit/tests`, {
    data: { name: 'buon punteggio', input: { score: 700 }, expected: { outcome: 'valid' } },
  })
  const published = await request.post(`${ws}/rulesets/credit/publish`, { data: { promoteTo: 'prod' } })
  expect(published.status()).toBe(201)
  await request.put(`${ws}/rulesets/credit/draft`, { data: { graph: graph(650) } })

  await page.goto('/w/aurora/rulesets/credit')
  await page.getByRole('tab', { name: 'Versioni' }).click()
  const panel = page.locator('.editor-panel')

  // what changed since 0.1.0
  await panel.getByRole('button', { name: 'Confronta con il draft' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('constants.minimum: 600 → 650')).toBeVisible()
  await dialog.getByRole('button', { name: 'Chiudi' }).click()

  // publish 0.2.0 and schedule it in prod from a date
  await panel.getByRole('button', { name: 'Pubblica…' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Pubblica', exact: true }).click()
  await expect(panel.getByText('Pubblicata la versione 0.2.0.')).toBeVisible()
  await panel.getByRole('button', { name: 'Porta in…' }).first().click()
  await page.getByRole('radio', { name: /Da una data/ }).check()
  await page.getByLabel('In vigore dal').fill('2030-01-01')
  await page.getByRole('dialog').getByRole('button', { name: 'Conferma' }).click()
  await expect(panel.getByText('dal 1 gennaio 2030')).toBeVisible()

  const call = (day: string) =>
    request.post(`${API}/exec/aurora/credit`, { data: { input: { score: 620 }, options: { referenceDate: day } } })
  await expect.poll(async () => (await (await call('2030-02-01')).json()).outcome, { timeout: 10_000 }).toBe('invalid')
  expect((await (await call('2029-12-31')).json()).outcome).toBe('valid')

  // export the draft and import it into another workspace
  const download = page.waitForEvent('download')
  await page.locator('.editor-toolbar').getByRole('button', { name: 'Esporta' }).click()
  const file = await (await download).path()
  const bundle = JSON.parse(readFileSync(file, 'utf8')) as { format: string; tests: unknown[] }
  expect(bundle.format).toBe('minos-bundle/1')
  expect(bundle.tests).toHaveLength(1)

  await request.post(`${API}/workspaces`, { data: { slug: 'copia', name: 'Copia' } })
  await page.goto('/w/copia')
  await page.getByLabel('File da importare').setInputFiles(file)
  await expect(page).toHaveURL(/\/w\/copia\/rulesets\/credit$/)
  await expect(page.locator('.react-flow__node[data-id="score"]')).toBeVisible()
  await page.getByRole('tab', { name: 'Test' }).click()
  await expect(panel.getByText('buon punteggio')).toBeVisible()
})
