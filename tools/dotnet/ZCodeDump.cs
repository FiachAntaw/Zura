using System; using System.Linq; using System.Reflection; using System.IO; using System.IO.Compression; using System.Collections.Generic;
var asm = Assembly.LoadFrom(args[0]);
Type[] types; try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException e) { types = e.Types.Where(t => t != null).ToArray(); }
var baseT = asm.GetType("RQvm0RAEXMITK976d0P.svBKt4AWJuPHGcKPI87", true);
var byOp = new Dictionary<byte, Type>();
foreach (var t in types.Where(t => !t.IsAbstract && baseT.IsAssignableFrom(t))) {
  try {
    var o = Activator.CreateInstance(t);
    byte op = (byte)t.GetMethod("onEomVmEYtu").Invoke(o, null);
    string name = (string)t.GetMethod("rknomFGAmSL").Invoke(o, null);
    var fields = string.Join(", ", t.GetFields(BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public|BindingFlags.DeclaredOnly).Select(f => f.FieldType.Name));
    Console.WriteLine($"OP {op,3} 0x{op:x2} {name,-28} {t.FullName} [{fields}]");
    byOp.TryAdd(op, t);
  } catch (Exception e) { Console.WriteLine($"ERR {t.FullName}: {e.InnerException?.Message ?? e.Message}"); }
}
if (args.Length > 1) {
  var zc = File.ReadAllBytes(args[1]);
  using var w = new StreamWriter(args[2]);
  int i = 0; while (i < zc.Length) { int len = zc[i]; var rec = zc.Skip(i).Take(len + 1).ToArray(); byte op = zc[i + 1];
    if (byOp.TryGetValue(op, out var t)) { var o = Activator.CreateInstance(t); bool ok = (bool)t.GetMethod("FromBytes").Invoke(o, new object[]{rec}); w.WriteLine((ok ? "" : "!BAD ") + o.ToString()); }
    else w.WriteLine($"?? op {op} {BitConverter.ToString(rec)}");
    i += len + 1; }
}
