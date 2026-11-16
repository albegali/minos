// Gate G2: a business user builds, tests and publishes a rule set using only Minos Studio —
// no JSON written by hand, no developer involved. The installation is open (the default):
// no login, as for a local deployment.

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, type Locator, type Page, test } from '@playwright/test'

const here = dirname(fileURLToPath(import.meta.url))
const examples = join(here, '..', '..', 'examples', 'inputs')
const validPlan = readFileSync(join(examples, 'studyplan-emba-valid.json'), 'utf8')
const invalidPlan = readFileSync(join(examples, 'studyplan-emba-invalid.json'), 'utf8')

async function pick(page: Page, combobox: Locator, option: string | RegExp, type?: string) {
  await combobox.click()
  if (type) await combobox.fill(type)
  await page.getByRole('option', { name: option, exact: typeof option === 'string' }).first().click()
}

/** Drag from an output port of `from` to the input of `to` on the React Flow canvas. */
async function wire(page: Page, from: string, port: string, to: string) {
  const src = page.locator(`.react-flow__node[data-id="${from}"] .react-flow__handle.source[data-handleid="${port}"]`)
  const dst = page.locator(`.react-flow__node[data-id="${to}"] .react-flow__handle.target`)
  const a = await src.boundingBox()
  const b = await dst.boundingBox()
  if (!a || !b) throw new Error(`handles not visible: ${from}:${port} -> ${to}`)
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 })
  await page.mouse.up()
}

test('an open installation needs no login', async ({ page }) => {
  await page.goto('/login')
  await expect(page).toHaveURL(/\/w$/)
  await expect(page.getByRole('heading', { name: 'Workspace' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Esci' })).toHaveCount(0)
})

test('a business user builds, tests and publishes a rule set from the Studio', async ({ page, request }) => {
  // Open the workspace (no login on an open installation)
  await page.goto('/')
  await page.getByText('Aurora Business School').click()
  await expect(page).toHaveURL(/\/w\/aurora$/)

  // Entity and schema inferred from an example
  await page.getByRole('button', { name: 'Nuova entità' }).click()
  await page.getByLabel('Nome').fill('Study Plan')
  await page.getByLabel('Chiave').fill('StudyPlan')
  await page.getByRole('button', { name: 'Crea' }).click()
  await expect(page).toHaveURL(/\/entities\/StudyPlan$/)
  await page.getByLabel('Esempi (un oggetto o una lista di oggetti)').fill(`[${validPlan}, ${invalidPlan}]`)
  await expect(page.getByRole('cell', { name: '$.input.courses[*].cfu' })).toBeVisible()
  await page.getByRole('button', { name: 'Salva come nuova versione' }).click()
  await expect(page.getByRole('tab', { name: /v1/ })).toBeVisible()

  // Rule set
  await page.getByRole('button', { name: 'aurora' }).click()
  await page.getByRole('button', { name: 'Nuovo rule set' }).click()
  await page.getByLabel('Nome').fill('Piano EMBA')
  await pick(page, page.getByRole('combobox', { name: /Entità/ }), 'StudyPlan')
  await page.getByRole('button', { name: 'Crea' }).click()
  await expect(page).toHaveURL(/\/rulesets\/piano-emba$/)
  await expect(page.locator('.react-flow__node[data-id="start"]')).toBeVisible()

  // Drag a condition from the palette onto the canvas
  await page
    .getByRole('button', { name: /^Condizione/ })
    .dragTo(page.locator('.react-flow__pane'), { targetPosition: { x: 420, y: 520 } })
  const node = page.locator('.react-flow__node[data-id="condition1"]')
  await expect(node).toBeVisible()

  // Configure it: "sum of the CFU of the courses >= 60", with a message when it fails
  const panel = page.locator('.editor-panel')
  await panel.getByLabel('Etichetta').fill('CFU minimi')
  await pick(page, panel.getByRole('combobox', { name: 'Tipo di espressione', exact: true }).first(), 'Su una lista')
  await pick(page, panel.getByRole('combobox', { name: 'Funzione sulla lista', exact: true }), 'somma')
  await pick(page, panel.getByRole('combobox', { name: 'Lista', exact: true }), '$.input.courses', 'courses')
  await panel.getByLabel('Usa un valore calcolato da ogni elemento').check()
  await pick(page, panel.getByRole('combobox', { name: 'Campo', exact: true }), '$.item.cfu', 'cfu')
  await pick(page, panel.getByRole('combobox', { name: 'Operatore', exact: true }), 'è maggiore o uguale a')
  await panel.getByRole('textbox', { name: 'Valore' }).fill('60')
  await panel.getByLabel('Messaggio se fallisce').check()
  await panel.getByRole('textbox', { name: 'Codice' }).fill('SP_CFU_MIN')
  await panel.getByRole('textbox', { name: 'Messaggio (it)' }).fill('Servono almeno 60 CFU')
  await expect(node).toContainText('sum(courses di item.cfu) ≥ 60')

  // Wire start -> condition -> end (replaces the starter edge start -> end)
  await wire(page, 'start', 'next', 'condition1')
  await wire(page, 'condition1', 'pass', 'end')
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)

  // Collect every error rather than stopping at the first
  await page.getByRole('tab', { name: 'Impostazioni' }).click()
  await pick(page, panel.getByRole('combobox', { name: /Modalità/ }), 'Raccogli tutti gli errori')

  // Save and validate (type-checked against the schema on the server)
  await page.getByRole('button', { name: 'Valida' }).click()
  await expect(page.locator('.editor-toolbar').getByText('Valido', { exact: true })).toBeVisible()
  await expect(page.getByText(/Salvato \(rev\. \d+\)/)).toBeVisible()

  // Simulate the invalid plan: 40 CFU
  await page.getByRole('tab', { name: 'Simulazione' }).click()
  await panel.getByLabel('Oggetto in input').fill(invalidPlan)
  await panel.getByRole('button', { name: 'Simula il draft' }).click()
  await expect(panel.getByText('Non valido')).toBeVisible()
  await expect(panel.getByText('Servono almeno 60 CFU')).toBeVisible()
  await expect(node.locator('.rule-node')).toHaveClass(/status-fail/)

  // Keep it as a regression test
  await panel.getByRole('button', { name: 'Salva questa simulazione come test' }).click()
  await page.getByLabel('Nome del test').fill('piano con 40 CFU')
  await page.getByRole('dialog').getByRole('button', { name: 'Salva', exact: true }).click()
  await page.getByRole('tab', { name: 'Test' }).click()
  await panel.getByRole('button', { name: 'Esegui i test sul draft' }).click()
  await expect(panel.getByText('ok', { exact: true })).toBeVisible()

  // Publish 0.1.0 straight to the test environment
  await page.getByRole('tab', { name: 'Versioni' }).click()
  await panel.getByRole('button', { name: 'Pubblica…' }).click()
  await pick(page, page.getByRole('combobox', { name: /Promuovi subito in/ }), 'test')
  await page.getByRole('dialog').getByRole('button', { name: 'Pubblica', exact: true }).click()
  await expect(panel.getByText('Pubblicata la versione 0.1.0 e promossa in test.')).toBeVisible()

  // A third-party system can now call it
  await expect
    .poll(
      async () => {
        const res = await request.post('http://127.0.0.1:8000/v1/exec/aurora/piano-emba@test', {
          data: { input: JSON.parse(validPlan) },
        })
        return res.ok() ? (await res.json()).outcome : res.status()
      },
      { timeout: 10_000 },
    )
    .toBe('valid')
  const res = await request.post('http://127.0.0.1:8000/v1/exec/aurora/piano-emba@test', {
    data: { input: JSON.parse(invalidPlan) },
  })
  const body = await res.json()
  expect(body.outcome).toBe('invalid')
  expect(body.feedback.map((f: { code: string }) => f.code)).toEqual(['SP_CFU_MIN'])
})
