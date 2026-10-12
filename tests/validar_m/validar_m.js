// Confere a sintaxe de todas as consultas Power Query (M) do modelo com o analisador oficial da Microsoft.
const fs = require("fs");
const PQP = require("@microsoft/powerquery-parser");
const db = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const m = db.model;
const consultas = [];
for (const e of m.expressions || []) consultas.push([`parâmetro/consulta ${e.name}`, [].concat(e.expression).join("\n")]);
for (const t of m.tables) for (const p of t.partitions || []) if (p.source.type === "m") consultas.push([`tabela ${t.name}`, [].concat(p.source.expression).join("\n")]);
let falhas = 0;
(async () => {
  for (const [nome, texto] of consultas) {
    const r = await PQP.TaskUtils.tryLexParse(PQP.DefaultSettings, texto);
    if (PQP.TaskUtils.isOk(r)) console.log(`ok   ${nome}`);
    else { falhas++; console.log(`ERRO ${nome}: ${r.error && r.error.message}`); }
  }
  console.log(`${consultas.length} consultas, ${falhas} com erro de sintaxe`);
  process.exit(falhas ? 1 : 0);
})();
