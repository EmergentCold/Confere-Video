// Abre o ConfereVideo.html direto do disco (file://, como dois cliques), confere a demonstração
// e falha se o resultado não for o do programa: 10 itens e os 4 erros, um de cada tipo.
const { chromium } = require('playwright');
(async () => {
  const arq = process.argv[2], foto = process.argv[3];
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const logs = [];
  p.on('pageerror', e => logs.push('pageerror: ' + e.message));
  p.on('console', m => { if (m.type() === 'error' || m.text().startsWith('[diagn')) logs.push(m.type() + ': ' + m.text().slice(0, 250)); });
  await p.goto('file://' + arq);
  await p.waitForFunction(() => typeof fonte !== 'undefined' && fonte.url, null, { timeout: 60000 });
  const t0 = Date.now();
  await p.click('#bt-conferir');
  await p.waitForFunction(() => window.__resultado, null, { timeout: 900000, polling: 2000 });
  const res = await p.evaluate(() => window.__resultado);
  console.log('tempo', Math.round((Date.now() - t0) / 1000), 's', JSON.stringify(res));
  await p.screenshot({ path: foto });
  console.log(logs.join('\n'));
  await b.close();
  const r = JSON.parse(JSON.stringify(res));
  if (r.itens !== 10 || JSON.stringify(r.erros) !== JSON.stringify(['sem_leitor', 'bipe_duplo', 'caixa_errada', 'sem_bipe'])) { console.error('resultado diferente do esperado'); process.exit(1); }
  console.log('OK: mesmo resultado do programa instalado.');
})().catch((e) => { console.error(e); process.exit(1); });
