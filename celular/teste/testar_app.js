// Abre o ConfereVídeo no emulador Android, confere a demonstração e confere o resultado
// (o mesmo do programa instalado: 10 itens, 4 erros — um de cada tipo).
const { _android: android } = require("playwright-core");
const PKG = "com.emergentcold.conferevideo";
const ESPERADO = ["sem_leitor", "bipe_duplo", "caixa_errada", "sem_bipe"];

(async () => {
  const [device] = await android.devices();
  if (!device) throw new Error("nenhum emulador encontrado");
  console.log("Aparelho:", device.model(), device.serial());
  await device.shell(`am force-stop ${PKG}`);
  await device.shell(`am start -n ${PKG}/.MainActivity`);
  const webview = await device.webView({ pkg: PKG }, { timeout: 180000 });
  const page = await webview.page();
  page.on("pageerror", (e) => console.log("pageerror:", e.message));
  page.on("console", (m) => console.log("console:", m.type(), m.text()));
  await page.waitForFunction(() => typeof fonte !== "undefined" && fonte.url && !document.querySelector("#bt-conferir").disabled, null, { timeout: 180000 });
  await device.screenshot({ path: "celular/teste/1_inicio.png" });
  const t0 = Date.now();
  await page.click("#bt-conferir");
  await page.waitForFunction(() => window.__resultado, null, { timeout: 40 * 60000, polling: 5000 });
  const r = await page.evaluate(() => window.__resultado);
  console.log(`Conferência em ${Math.round((Date.now() - t0) / 1000)} s:`, JSON.stringify(r));
  await device.screenshot({ path: "celular/teste/2_resultado.png" });
  await page.click("#aba-relatorio");
  await device.screenshot({ path: "celular/teste/3_relatorio.png" });
  await device.close();
  if (r.falha) throw new Error("a conferência falhou: " + r.falha);
  if (r.itens !== 10 || JSON.stringify(r.erros) !== JSON.stringify(ESPERADO)) throw new Error("resultado diferente do esperado (10 itens e " + ESPERADO.join(", ") + ")");
  console.log("OK: mesmo resultado do programa instalado.");
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
