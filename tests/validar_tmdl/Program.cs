// uso: dotnet run -- PASTA_DO_MODELO/definition SAIDA.json
using Microsoft.AnalysisServices.Tabular;

if (args.Length < 2) { Console.Error.WriteLine("uso: validar_tmdl PASTA_TMDL SAIDA.json"); return 2; }
try
{
    var db = TmdlSerializer.DeserializeDatabaseFromFolder(args[0]);
    var m = db.Model;
    Console.WriteLine($"Modelo lido: nível {db.CompatibilityLevel}, {m.Tables.Count} tabelas, " +
                      $"{m.Tables.Sum(t => t.Measures.Count)} medidas, {m.Relationships.Count} relações, " +
                      $"{m.Expressions.Count} consultas/parâmetros");
    // ida e volta: TMDL -> TOM -> TMDL (o que o Power BI faz ao salvar)
    var tmp = Path.Combine(Path.GetTempPath(), "tmdl_volta_" + Guid.NewGuid().ToString("N"));
    TmdlSerializer.SerializeDatabaseToFolder(db, tmp);
    var db2 = TmdlSerializer.DeserializeDatabaseFromFolder(tmp);
    Directory.Delete(tmp, true);
    if (db2.Model.Tables.Count != m.Tables.Count) throw new Exception("ida e volta perdeu tabelas");
    File.WriteAllText(args[1], JsonSerializer.SerializeDatabase(db));
    return 0;
}
catch (Exception e)
{
    Console.Error.WriteLine("TMDL inválido: " + e.Message);
    return 1;
}
