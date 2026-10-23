using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Web.WebView2.WinForms;

namespace SabagRobot;

/// <summary>
/// Desktop window for the robot app: starts the local Python server if it isn't running,
/// shows the web app in WebView2, and stops the server it started when the window closes.
/// </summary>
internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new RobotWindow());
    }
}

internal sealed class RobotWindow : Form
{
    private const string AppUrl = "http://127.0.0.1:8765/";
    private static readonly Color Ink = Color.FromArgb(0x15, 0x1a, 0x2b);

    // The exe lives in launcher\publish; the project root is two levels up.
    private static readonly string ProjectRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", ".."));

    private readonly WebView2 _web = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Ink };
    private readonly Label _splash = new()
    {
        Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, ForeColor = Color.FromArgb(0x9a, 0xa6, 0xc4),
        Font = new Font("Segoe UI", 13f), Text = "מפעיל את השרת של הרובוט…", RightToLeft = RightToLeft.Yes,
    };
    private Process? _server;

    public RobotWindow()
    {
        Text = "Sabag Robot";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        BackColor = Ink;
        ClientSize = new Size(460, 900);
        MinimumSize = new Size(380, 600);
        StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(_web);
        Controls.Add(_splash);
        _splash.BringToFront();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        // Dark title bar to match the app (Windows 10 2004+ / 11).
        int dark = 1;
        DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int));
    }

    protected override async void OnShown(EventArgs e)
    {
        base.OnShown(e);
        try
        {
            if (!await ServerAnswers())
            {
                StartServer();
                if (!await WaitForServer(TimeSpan.FromSeconds(25)))
                {
                    _splash.Text = "השרת לא עלה. הפרטים ב-data\\server.log";
                    return;
                }
            }
            var userData = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SabagRobot");
            var env = await Microsoft.Web.WebView2.Core.CoreWebView2Environment.CreateAsync(null, userData);
            await _web.EnsureCoreWebView2Async(env);
            _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            _web.CoreWebView2.Navigate(AppUrl);
            _web.CoreWebView2.NavigationCompleted += (_, _) => _splash.Visible = false;
        }
        catch (Exception ex)
        {
            _splash.Text = "לא הצלחתי לפתוח את האפליקציה:\n" + ex.Message;
        }
    }

    private void StartServer()
    {
        var python = Path.Combine(ProjectRoot, ".venv", "Scripts", "python.exe");
        var log = Path.Combine(ProjectRoot, "data", "server.log");
        Directory.CreateDirectory(Path.GetDirectoryName(log)!);
        var info = new ProcessStartInfo(python, "-X utf8 -m server --host 0.0.0.0")
        {
            WorkingDirectory = ProjectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        _server = Process.Start(info);
        if (_server is null) return;
        var writer = new StreamWriter(log, append: true) { AutoFlush = true };
        _server.OutputDataReceived += (_, a) => { if (a.Data is not null) lock (writer) writer.WriteLine(a.Data); };
        _server.ErrorDataReceived += (_, a) => { if (a.Data is not null) lock (writer) writer.WriteLine(a.Data); };
        _server.BeginOutputReadLine();
        _server.BeginErrorReadLine();
    }

    private static async Task<bool> ServerAnswers()
    {
        try
        {
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            return (await http.GetAsync(AppUrl + "api/state")).IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private static async Task<bool> WaitForServer(TimeSpan limit)
    {
        var until = DateTime.UtcNow + limit;
        while (DateTime.UtcNow < until)
        {
            if (await ServerAnswers()) return true;
            await Task.Delay(500);
        }
        return false;
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        // Only stop a server this window started; one started elsewhere keeps running.
        if (_server is { HasExited: false }) _server.Kill(entireProcessTree: true);
        base.OnFormClosed(e);
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
}
