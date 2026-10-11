using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Themes.Fluent;
using Avalonia.Styling;
using System.Diagnostics;

namespace Punctora.Desktop;

public sealed class App : Application
{
    public override void Initialize(){RequestedThemeVariant=ThemeVariant.Dark;Styles.Add(new FluentTheme());}
    public override void OnFrameworkInitializationCompleted()
    {
        if(ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            desktop.MainWindow=new MainWindow(desktop.Args??[]);
        base.OnFrameworkInitializationCompleted();
    }
}

public static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        Trace.Listeners.Add(new TextWriterTraceListener(Console.Error));Trace.AutoFlush=true;
        var x11=new X11PlatformOptions{RenderingMode=[X11RenderingMode.Egl,X11RenderingMode.Glx,X11RenderingMode.Software]};
        // CI has no physical GPU. Explicitly allow Mesa only for verification
        // so the OpenGL code is exercised instead of silently using fallback.
        if(args.Contains("--verify-ui")&&Environment.GetEnvironmentVariable("PUNCTORA_TEST_SOFTWARE_GL")=="1")
            x11.GlxRendererBlacklist=[];
        var result=AppBuilder.Configure<App>().UsePlatformDetect()
            .With(x11)
            .LogToTrace().StartWithClassicDesktopLifetime(args);
        return Environment.ExitCode!=0?Environment.ExitCode:result;
    }
}
