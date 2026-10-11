using System.Text.Json.Nodes;
using Punctora.Desktop;

if (args.Length != 1) throw new ArgumentException("Pass the large worker fixture project");
var path = Path.GetFullPath(args[0]);
var client = new WorkerClient();
var request = new JsonObject { ["command"] = "open", ["project"] = path,
    ["large_request_probe"] = new string('y', 20 * 1024 * 1024) };
var result = await client.RunAsync(request, null, CancellationToken.None);
if (result["warnings"]![0]!.GetValue<string>() != new string('x', 20 * 1024 * 1024)
    || result["transport_probe"]!["record_id"]!.GetValue<long>() != (1L << 53) + 17
    || result["transport_probe"]!["coordinate"]!.GetValue<double>() != 125.123456789)
    throw new Exception("Large result lost evidence, source identity or coordinate precision");
var id = request["job_id"]!.GetValue<string>();
if (client.ActiveProcess != null || Directory.Exists(Path.Combine(Path.GetTempPath(), "punctora-worker-" + id)))
    throw new Exception("Completed worker exchange was not cleaned up");
using var cancelled = new CancellationTokenSource();
cancelled.Cancel();
try { await client.RunAsync(new JsonObject(), null, cancelled.Token); throw new Exception("Cancellation ignored"); }
catch (OperationCanceledException) { }
var missing = new JsonObject { ["command"] = "open", ["project"] = Path.Combine(Path.GetDirectoryName(path)!, "missing.punctora") };
try { await client.RunAsync(missing, null, CancellationToken.None); throw new Exception("Worker error ignored"); }
catch (InvalidOperationException e) when (e.Message.Contains("No such file") || e.Message.Contains("cannot find")) { }
if (Directory.Exists(Path.Combine(Path.GetTempPath(), "punctora-worker-" + missing["job_id"]!.GetValue<string>())))
    throw new Exception("Failed worker exchange was not cleaned up");
Console.WriteLine("Desktop worker verified: 20 MiB request/result, exact identities, precision, cancellation and cleanup.");
