using System;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;
using System.Text;
using System.Threading;
public sealed class FravenirSupervisor : ServiceBase
{
    private readonly object gate = new object();
    private readonly string app = @"C:\ProgramData\Fravenir\app";
    private readonly string logs = @"C:\ProgramData\Fravenir\logs";
    private readonly string cli = @"C:\ProgramData\Fravenir\venv\Scripts\fravenir.exe";
    private readonly string python = @"C:\ProgramData\Fravenir\venv\Scripts\python.exe";
    private Process backend, bridge, admin, boardGate;
    private Timer monitor;
    private DateTime backendRetry = DateTime.MinValue, bridgeRetry = DateTime.MinValue, adminRetry = DateTime.MinValue, boardGateRetry = DateTime.MinValue;
    public FravenirSupervisor() { ServiceName = "FravenirMCP"; CanStop = true; AutoLog = false; }
    protected override void OnStart(string[] args)
    {
        Directory.CreateDirectory(logs);
        WriteLog("Supervisor starting.");
        lock (gate) EnsureProcess(ref backend, cli, "serve --character main --transport streamable-http --host 127.0.0.1 --port 8280", "mcp", ref backendRetry);
        monitor = new Timer(_ => MonitorChildren(), null, 3000, 5000);
    }
    private void MonitorChildren()
    {
        lock (gate)
        {
            if (monitor == null) return;
            EnsureProcess(ref backend, cli, "serve --character main --transport streamable-http --host 127.0.0.1 --port 8280", "mcp", ref backendRetry);
            EnsureProcess(ref bridge, python, "-m uvicorn deploy.windows.oauth_bridge:app --host 127.0.0.1 --port 8001 --workers 1", "bridge", ref bridgeRetry);
            EnsureProcess(ref admin, python, "-c \"import uvicorn; from fravenir.admin.server import create_app; uvicorn.run(create_app('main'), host='127.0.0.1', port=8281)\"", "admin", ref adminRetry);
            EnsureProcess(ref boardGate, python, "-m uvicorn deploy.windows.board_auth:app --host 127.0.0.1 --port 8282 --proxy-headers --forwarded-allow-ips 127.0.0.1 --env-file C:\\ProgramData\\PlanetOAuth\\oauth.env", "board-auth", ref boardGateRetry);
        }
    }
    private void EnsureProcess(ref Process child, string executable, string arguments, string name, ref DateTime retryAt)
    {
        try
        {
            if (child != null && !child.HasExited) return;
            if (child != null) { int oldPid = child.Id; child.Dispose(); child = null; WriteLog(name + " exited (pid " + oldPid + "); restarting."); retryAt = DateTime.UtcNow.AddSeconds(3); }
            if (DateTime.UtcNow < retryAt) return;
            var psi = new ProcessStartInfo(executable, arguments);
            psi.WorkingDirectory = app; psi.UseShellExecute = false; psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true; psi.RedirectStandardError = true;
            psi.StandardOutputEncoding = Encoding.UTF8; psi.StandardErrorEncoding = Encoding.UTF8;
            psi.EnvironmentVariables["PYTHONUTF8"] = "1";
            var p = new Process(); p.StartInfo = psi;
            p.OutputDataReceived += (s, e) => { if (e.Data != null) Append(name + ".out.log", e.Data); };
            p.ErrorDataReceived += (s, e) => { if (e.Data != null) Append(name + ".err.log", e.Data); };
            p.Start(); p.BeginOutputReadLine(); p.BeginErrorReadLine(); child = p;
            WriteLog("Started " + name + " (pid " + p.Id + ").");
            retryAt = DateTime.UtcNow.AddSeconds(3);
        }
        catch (Exception ex) { WriteLog("Could not start " + name + ": " + ex.GetType().Name + ": " + ex.Message); retryAt = DateTime.UtcNow.AddSeconds(10); }
    }
    protected override void OnStop()
    {
        lock (gate) { if (monitor != null) { monitor.Dispose(); monitor = null; } StopChild(ref boardGate, "board-auth"); StopChild(ref admin, "admin"); StopChild(ref bridge, "bridge"); StopChild(ref backend, "mcp"); WriteLog("Supervisor stopped."); }
    }
    private void StopChild(ref Process child, string name)
    {
        if (child == null) return;
        try { if (!child.HasExited) { child.Kill(); child.WaitForExit(10000); } } catch (Exception ex) { WriteLog("Stopping " + name + " failed: " + ex.Message); }
        try { child.Dispose(); } catch { } child = null;
    }
    private void WriteLog(string line) { Append("supervisor.log", DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + line); }
    private void Append(string file, string line) { try { File.AppendAllText(Path.Combine(logs, file), line + Environment.NewLine, new UTF8Encoding(false)); } catch { } }
    public static void Main() { ServiceBase.Run(new FravenirSupervisor()); }
}
