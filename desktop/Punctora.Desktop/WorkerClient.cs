using System.Diagnostics;
using System.Text.Json.Nodes;

namespace Punctora.Desktop;

public sealed class WorkerClient
{
    public Process? ActiveProcess { get; private set; }
    public static string? RepositoryRoot()
    {
        foreach (var start in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
            for (DirectoryInfo? dir = new(start); dir != null; dir = dir.Parent)
                if (File.Exists(Path.Combine(dir.FullName, "pyproject.toml")) && Directory.Exists(Path.Combine(dir.FullName, "src", "punctora_core")))
                    return dir.FullName;
        return null;
    }

    public static string PythonExecutable()
    {
        var configured = Environment.GetEnvironmentVariable("PUNCTORA_PYTHON");
        if (!string.IsNullOrWhiteSpace(configured)) return configured;
        var bundled = Path.Combine(AppContext.BaseDirectory, "worker", "python", OperatingSystem.IsWindows() ? "python.exe" : "python");
        if (File.Exists(bundled)) return bundled;
        var root = RepositoryRoot();
        var local = root == null ? null : Path.Combine(root, ".venv", OperatingSystem.IsWindows() ? "Scripts" : "bin", OperatingSystem.IsWindows() ? "python.exe" : "python");
        return local != null && File.Exists(local) ? local : OperatingSystem.IsWindows() ? "python.exe" : "python3";
    }

    public async Task<JsonObject> RunAsync(JsonObject request, Action<int, string>? progress, CancellationToken cancellation)
    {
        if (ActiveProcess != null) throw new InvalidOperationException("A job is already running");
        var id = Guid.NewGuid().ToString("N");
        request["protocol_version"] = 1;
        request["job_id"] = id;
        var start = new ProcessStartInfo(PythonExecutable())
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true
        };
        start.ArgumentList.Add("-m"); start.ArgumentList.Add("punctora_core.worker");
        var root = RepositoryRoot();
        if (root != null) start.Environment["PYTHONPATH"] = Path.Combine(root, "src");
        start.Environment["PYTHONUNBUFFERED"] = "1";
        using var process = new Process { StartInfo = start };
        ActiveProcess = process;
        try
        {
            cancellation.ThrowIfCancellationRequested();
            if (!process.Start()) throw new InvalidOperationException("Could not start the geometry worker");
            using var registration = cancellation.Register(() =>
            {
                try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
                catch (InvalidOperationException) { }
                catch (System.ComponentModel.Win32Exception) { }
            });
            var diagnostics = process.StandardError.ReadToEndAsync();
            await process.StandardInput.WriteLineAsync(request.ToJsonString());
            process.StandardInput.Close();
            JsonObject? result = null;
            string? error = null;
            while (await process.StandardOutput.ReadLineAsync() is { } line)
            {
                if (line.Length > 16 * 1024 * 1024) throw new InvalidDataException("Worker response exceeds the message budget");
                var message = JsonNode.Parse(line)?.AsObject() ?? throw new InvalidDataException("Empty worker response");
                if (message["protocol_version"]?.GetValue<int>() != 1 || message["job_id"]?.GetValue<string>() != id)
                    throw new InvalidDataException("Unexpected worker protocol or job identity");
                switch (message["type"]?.GetValue<string>())
                {
                    case "progress": progress?.Invoke(message["percent"]!.GetValue<int>(), message["phase"]!.GetValue<string>()); break;
                    case "result": result = message["result"]!.DeepClone().AsObject(); break;
                    case "error": error = message["message"]!.GetValue<string>(); break;
                    default: throw new InvalidDataException("Unexpected worker message type");
                }
            }
            await process.WaitForExitAsync();
            var stderr = await diagnostics;
            // A complete result already received is authoritative if cancellation raced completion.
            if (result != null && process.ExitCode == 0) return result;
            cancellation.ThrowIfCancellationRequested();
            throw new InvalidOperationException(error ?? (string.IsNullOrWhiteSpace(stderr) ? "The geometry job ended without a result" : stderr.Trim()));
        }
        catch (Exception) when (cancellation.IsCancellationRequested)
        {
            throw new OperationCanceledException(cancellation);
        }
        finally
        {
            try { if (!process.HasExited) { process.Kill(true); await process.WaitForExitAsync(); } }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
            ActiveProcess = null;
        }
    }
}
