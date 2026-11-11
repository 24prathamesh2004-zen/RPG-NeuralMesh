// Browser check of the NeuralMesh UI against the running stack (Vite on 5173, API on 8000, stand-in model on 11435).
//
//   mkdir -p /tmp/pw && cd /tmp/pw && npm init -y && npm install playwright@1.64.1 && npx playwright install chromium
//   cp <app>/evaluations/ui_render_check.mjs /tmp/pw/ && cd /tmp/pw && node ui_render_check.mjs /tmp/pw/shots
//
// Signs in with the demo presenter account, asks the flagship question with no node chosen, a reworded question, an
// unmatched question, and a question while the stand-in misbehaves (the check step must hide the answer), then opens
// Mesh Nodes, Governance and the Dashboard. Screenshots go to the folder given as the first argument.
import { chromium } from 'playwright'

const BASE = process.env.UI_URL || 'http://127.0.0.1:5173'
const STANDIN = 'http://127.0.0.1:11435/control'
const SHOTS = process.argv[2] || '.'
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

try {
  // Sign in with a demo account
  await page.goto(`${BASE}/auth`, { waitUntil: 'networkidle' })
  await page.fill('input[type=email]', 'presenter@neuralmesh.local')
  await page.fill('input[type=password]', 'MeshPilot!2026')
  await page.click('button[type=submit]')
  await page.waitForSelector('#mesh-question', { timeout: 20000 })
  check('sign in lands on the Ask page', page.url().endsWith('/ask'), page.url())

  // Flagship question, no node chosen
  const chooser = page.locator('fieldset legend input[type=checkbox]')
  check('node choice is off by default', !(await chooser.isChecked()))
  await Promise.all([page.waitForResponse((r) => r.url().includes('/mesh/query'), { timeout: 120000 }), page.click('.ask-submit-button')])
  await page.waitForSelector('.ask-results-grid', { timeout: 90000 })
  const panels = await page.locator('.mesh-answer-panel').allInnerTexts()
  const routing = panels.find((t) => t.startsWith('Routed')) || ''
  check('routing panel says the graph routed it', routing.includes('Routed by the mesh graph'), routing.split('\n')[0])
  check('routing names CEAT and Harrisons', routing.includes('CEAT') && routing.includes('Harrisons'), routing.split('\n')[1] || '')
  const answer = panels.find((t) => t.startsWith('Answer')) || ''
  check('an answer is shown', answer.length > 40, answer.slice(0, 120).replace(/\n/g, ' '))
  // a citation shows as the number of its evidence card ("[2]"), or as the id of an item that has no card
  check('answer sentences carry citations', (answer.match(/\[(?:\d+|[a-z]+:[A-Za-z0-9#:._/-]+)\]/g) || []).length >= 2)
  const links = panels.find((t) => t.startsWith('Approved links')) || ''
  check('approved links panel shows the gap link', links.includes('addresses the gap in'), links.split('\n')[1] || '')
  const sources = await page.locator('.ask-source').count()
  check('evidence cards are listed', sources > 0, `${sources} cards`)
  const withheld = await page.locator('.withheld-panel').innerText().catch(() => '')
  check('withheld panel names the formulation record', withheld.includes('formulation') || withheld.includes('Formulation'), withheld.split('\n').slice(0, 3).join(' | '))
  check('no canary string on the page', !(await page.content()).includes('CANARY-'))
  await page.screenshot({ path: `${SHOTS}/ask-flagship.png`, fullPage: true })

  // Reworded question: routed by meaning
  await page.fill('#mesh-question', 'latex going bad before it reaches the factory')
  await Promise.all([page.waitForResponse((r) => r.url().includes('/mesh/query'), { timeout: 120000 }), page.click('.ask-submit-button')])
  await page.waitForSelector('.ask-results-grid', { timeout: 90000 })
  const routing2 = (await page.locator('.mesh-answer-panel').allInnerTexts()).find((t) => t.startsWith('Routed')) || ''
  check('reworded question routes to Harrisons', routing2.includes('Harrisons'), routing2.replace(/\n/g, ' | '))
  await page.screenshot({ path: `${SHOTS}/ask-reworded.png`, fullPage: true })

  // A question whose wording matches no company: it goes to the asker's own company (the presenter's is Zensar),
  // and the routing panel says so instead of leaving a dead end
  await page.fill('#mesh-question', 'tell me about the weather tomorrow')
  await Promise.all([page.waitForResponse((r) => r.url().includes('/mesh/query'), { timeout: 120000 }), page.click('.ask-submit-button')])
  await page.waitForSelector('.ask-results-grid', { timeout: 90000 })
  const routing3 = (await page.locator('.mesh-answer-panel').allInnerTexts()).find((t) => t.startsWith('No company matched')) || ''
  check("unmatched question goes to the asker's own company and says so", routing3.includes('your own company was asked') && routing3.includes('Zensar'), routing3.replace(/\n/g, ' | '))

  // A misbehaving model: the check step must hide the answer and say why. Only when the stand-in is the answer model.
  const callsBefore = await fetch(STANDIN).then((r) => r.json()).then((j) => j.calls).catch(() => null)
  const standinInUse = callsBefore !== null && (await (async () => {
    await page.fill('#mesh-question', 'What storage practices does CEAT use for natural rubber lots?')
    await Promise.all([page.waitForResponse((r) => r.url().includes('/mesh/query'), { timeout: 120000 }), page.click('.ask-submit-button')])
    await page.waitForSelector('.ask-results-grid', { timeout: 90000 })
    return (await fetch(STANDIN).then((r) => r.json())).calls > callsBefore
  })())
  if (!standinInUse) console.log('SKIP  the answer model is not the stand-in, so the misbehaving-model check was not run')
  if (standinInUse) {
  await fetch(STANDIN, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ mode: 'invent-citation' }) })
  await page.fill('#mesh-question', "What rubber-compound learnings from CEAT could reduce Harrisons Malayalam's latex spoilage?")
  await page.selectOption('.ask-submit-row select', 'compliance')
  await Promise.all([page.waitForResponse((r) => r.url().includes('/mesh/query'), { timeout: 120000 }), page.click('.ask-submit-button')])
  await page.waitForSelector('.ask-results-grid', { timeout: 90000 })
  const alerts = await page.locator('.ask-results-section .mesh-alert.note').allInnerTexts()
  const hasAnswer = (await page.locator('.mesh-answer-panel').allInnerTexts()).some((t) => t.startsWith('Answer'))
  check('failed check hides the answer and shows the reason', !hasAnswer && alerts.some((a) => a.includes('failed')), alerts.join(' | ').slice(0, 160))
  await page.screenshot({ path: `${SHOTS}/ask-check-failed.png`, fullPage: true })
  await fetch(STANDIN, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ mode: 'ok' }) })
  await page.selectOption('.ask-submit-row select', 'problem_solving')
  }

  // Mesh Nodes: cards, profile, graph
  await page.goto(`${BASE}/nodes`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.mesh-node-card', { timeout: 30000 })
  const cards = await page.locator('.mesh-node-card').count()
  // the registry's node list, read through the page with the signed-in user's token
  const registered = await page.evaluate(async () => {
    const response = await fetch('/api/v1/mesh/nodes', { headers: { Authorization: `Bearer ${localStorage.getItem('rpg-neuralmesh-token')}` } })
    return (await response.json()).nodes.length
  })
  check('Mesh Nodes lists every registered node', cards === registered, `${cards} cards for ${registered} registered nodes`)
  await page.locator('.mesh-node-expand').first().click()
  const profile = await page.locator('.mesh-node-profile').first().innerText()
  check('node profile is shown from metadata', profile.includes('packs') && profile.includes('Concepts'), profile.slice(0, 120))
  await page.waitForSelector('.mesh-graph-canvas canvas', { timeout: 30000 })
  const hint = await page.locator('.mesh-graph-hint').innerText()
  const shownMatch = hint.match(/^(\d+) of (\d+) shown/)
  check('mesh graph opens on companies and datapoints, not every entity', !!shownMatch && Number(shownMatch[1]) < Number(shownMatch[2]) / 2, hint)
  await page.fill('.mesh-graph-search input', 'pre-coagulation')
  await page.click('.mesh-graph-search button[type=submit]')
  await page.waitForSelector('.mesh-graph-detail h3', { timeout: 10000 })
  const detail = await page.locator('.mesh-graph-detail').innerText()
  check('graph search selects the entity and lists its connections', detail.includes('Latex pre-coagulation') && detail.includes('MENTIONS'), detail.split('\n').slice(0, 3).join(' | '))
  await page.click('.mesh-graph-actions button:has-text("Tree from here")')
  const tree = await page.locator('.mesh-graph-hint').innerText()
  await page.keyboard.press('Escape')
  check('tree view opens from an entity and Escape leaves it', tree.startsWith('Tree from') && !(await page.locator('.mesh-graph-hint').innerText()).startsWith('Tree from'), tree)
  await page.screenshot({ path: `${SHOTS}/nodes.png`, fullPage: true })

  // Governance: links between companies tab
  await page.goto(`${BASE}/governance`, { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: /Links between companies/ }).click()
  await page.waitForSelector('.governance-request', { timeout: 30000 })
  const linkCards = await page.locator('.governance-request').allInnerTexts()
  const proposed = linkCards.find((t) => t.includes('proposed')) || ''
  check('governance lists the five links with one proposed', linkCards.length === 5 && proposed.length > 0, `${linkCards.length} links`)
  const approveButtons = await page.locator('.governance-request button:has-text("Approve for")').count()
  const waiting = await page.locator('.governance-request .mesh-result-state:has-text("Waiting for")').count()
  check('a company reviews only its own side: the Zensar presenter sees no approve button and the two waiting sides', approveButtons === 0 && waiting === 2, `${approveButtons} buttons, ${waiting} waiting`)
  await page.screenshot({ path: `${SHOTS}/governance-links.png`, fullPage: true })

  // Domains and Applications pages
  await page.goto(`${BASE}/domains`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.mesh-table', { timeout: 30000 })
  const domainHeads = await page.locator('.mesh-section-panel h2').allInnerTexts()
  check('domains page lists the core and inspection layers with their rules', domainHeads.includes('core') && domainHeads.includes('inspection'), domainHeads.join(', '))
  await page.screenshot({ path: `${SHOTS}/domains.png`, fullPage: true })
  await page.goto(`${BASE}/applications`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.app-cards .mesh-section-panel', { timeout: 30000 })
  const appHeads = await page.locator('.app-cards h2').allInnerTexts()
  check('applications page shows SkillForge and Snap and Score', appHeads.includes('SkillForge') && appHeads.includes('Snap and Score'), appHeads.join(', '))
  await page.screenshot({ path: `${SHOTS}/applications.png`, fullPage: true })

  // Dashboard renders
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.dashboard-page', { timeout: 30000 })
  await page.screenshot({ path: `${SHOTS}/dashboard.png`, fullPage: true })
  check('dashboard renders', true)
} catch (error) {
  check('script completed', false, String(error).slice(0, 300))
  await page.screenshot({ path: `${SHOTS}/failure.png`, fullPage: true }).catch(() => {})
} finally {
  check('no page errors', pageErrors.length === 0, pageErrors.join(' | ').slice(0, 200))
  await browser.close()
}
const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length} of ${results.length} browser checks passed`)
process.exit(failed.length ? 1 : 0)
