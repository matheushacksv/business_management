// Run: bun scripts/calculators.check.ts — compares the ported calculators with the client's original HTML math.
import assert from 'node:assert/strict'

const money = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
Object.assign(globalThis, { formatMoney: (v: number) => money.format(v), formatDate: (v: string) => v })
const { amountInWords, calcProfit, calcTermination, PLANS, PROFIT_DEFAULTS, TERMINATION_DEFAULTS } = await import('../app/utils/calculators')

// Words
assert.equal(amountInWords(1), 'um real')
assert.equal(amountInWords(1200), 'mil e duzentos reais')
assert.equal(amountInWords(5320.5), 'cinco mil, trezentos e vinte reais e cinquenta centavos')
assert.equal(amountInWords(100), 'cem reais')
assert.equal(amountInWords(21000.01), 'vinte e um mil reais e um centavo')

// Profit: 10.000 gross, defaults (tax 10%, advisor+closer 10% of 9.000, CAC 3.000, overhead 26,46%)
const p = calcProfit({ ...structuredClone(PROFIT_DEFAULTS), gross: 10000 })
assert.equal(p.afterTax, 9000)
assert.equal(Math.round(p.costs * 100) / 100, 1000 + 900 + 900 + 3000 + 2646)
assert.equal(Math.round(p.net * 100) / 100, 1554)

// Termination: original algorithm (rescisao-calculadora.html, calcular()) for preset plans
function original(planKey: string, total: number, paid: number, ent: Record<string, any>, add: Record<string, any>, fineOn: boolean, finePct: number, type: 'new' | 'old') {
  const P = PLANS[planKey]!.scope
  const temADP = P.adp || add.adp, temCRM = add.crm, temLanding = add.landing, mTraf = add.trafego ? add.meses : 0
  let fixos = (temADP ? 997 : 0) + (temCRM ? 4997 : 0) + (temLanding ? 2000 : 0) + mTraf * 2000
  const vVar = Math.max(0, total - fixos)
  let fe = (ent.adp && temADP ? 997 : 0) + (ent.crm && temCRM ? 4997 : 0) + (ent.landing && temLanding ? 2000 : 0)
  fe += (add.trafego ? ent.meses : 0) * 2000
  const eA = Math.min(ent.a, P.advisory), eS = Math.min(ent.s, P.success), eAp = Math.min(ent.ap, P.booklets)
  const w = { a: 0.5, s: 0.3, sc: 0.2, ap: 0 }
  if (P.success === 0) { w.a += w.s; w.s = 0 }
  const v = vVar * w.a * (P.advisory ? eA / P.advisory : 0) + vVar * w.s * (P.success ? eS / P.success : 0)
    + vVar * w.sc * (ent.scripts ? 1 : 0) + vVar * w.ap * (P.booklets ? eAp / P.booklets : 0) + fe
  const multa = fineOn ? (type === 'new' ? 5000 : 4554) * finePct / 100 : 0
  return Math.max(0, Math.max(0, total - paid) - Math.max(0, total - v) + multa)
}

let seed = 42
const rnd = (n: number) => { seed = (seed * 1103515245 + 12345) % 2 ** 31; return seed % n }
for (let k = 0; k < 500; k++) {
  const planKey = ['fast', 'growth', 'pro'][rnd(3)]!
  const total = 20000 + rnd(30000), paid = rnd(15000)
  const add = { adp: !!rnd(2), crm: !!rnd(2), landing: !!rnd(2), trafego: !!rnd(2), meses: 1 + rnd(4) }
  const ent = { a: rnd(5), s: rnd(5), ap: rnd(13), scripts: !!rnd(2), adp: !!rnd(2), crm: !!rnd(2), landing: !!rnd(2), meses: rnd(add.meses + 1) }
  const fineOn = !!rnd(2), finePct = rnd(21) * 5, type = rnd(2) ? 'new' as const : 'old' as const
  const base = PLANS[planKey]!.scope
  const input = {
    ...structuredClone(TERMINATION_DEFAULTS), total, paid, chargeFine: fineOn, finePct, contractType: type,
    contracted: { ...base, adp: base.adp || add.adp, crm: add.crm, landing: add.landing, trafficMonths: add.trafego ? add.meses : 0 },
    delivered: { ...base, advisory: ent.a, success: ent.s, booklets: ent.ap, scripts: ent.scripts, adp: ent.adp, crm: ent.crm, landing: ent.landing, trafficMonths: ent.meses },
  }
  const ours = calcTermination(input).due
  assert.ok(Math.abs(ours - original(planKey, total, paid, ent, add, fineOn, finePct, type)) < 0.005, `case ${k}`)
}
console.log('calculators ok')
