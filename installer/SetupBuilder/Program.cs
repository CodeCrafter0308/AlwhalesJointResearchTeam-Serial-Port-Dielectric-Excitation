using System.Diagnostics;
using System.Reflection;
using System.Runtime.Versioning;
using System.Windows.Forms;
using Microsoft.Win32;

namespace DataReceiveAndAnalysisSetup;

internal static class Program
{
    private const string AppId = "DataReceiveAndAnalysis";
    private const string AppName = "Data Receive and Analysis";
    private const string ExeName = "DataReceiveAndAnalysis.exe";
    private const string IconName = "app_icon.ico";

    [STAThread]
    [SupportedOSPlatform("windows")]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();

        try
        {
            string appPath = Install();
            DialogResult result = MessageBox.Show(
                "Data Receive and Analysis has been installed successfully.\n\nStart the software now?",
                "Installation Complete",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Information);

            if (result == DialogResult.Yes)
            {
                Process.Start(new ProcessStartInfo(appPath)
                {
                    WorkingDirectory = Path.GetDirectoryName(appPath),
                    UseShellExecute = true,
                });
            }
        }
        catch (Exception exc)
        {
            MessageBox.Show(
                "Installation failed. Close the software if it is running, then try again.\n\n" + exc.Message,
                "Installation Failed",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            Environment.ExitCode = 1;
        }
    }

    private static string Install()
    {
        string installDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs",
            AppId);
        Directory.CreateDirectory(installDir);

        string appPath = Path.Combine(installDir, ExeName);
        string iconPath = Path.Combine(installDir, IconName);
        ExtractResource(ExeName, appPath);
        ExtractResource(IconName, iconPath);

        string uninstallPath = Path.Combine(installDir, "Uninstall.ps1");
        File.WriteAllText(uninstallPath, BuildUninstallScript());

        CreateShortcut(
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), AppName + ".lnk"),
            appPath,
            iconPath);

        string startMenuDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), AppName);
        Directory.CreateDirectory(startMenuDir);
        CreateShortcut(Path.Combine(startMenuDir, AppName + ".lnk"), appPath, iconPath);

        RegisterUninstaller(installDir, appPath, uninstallPath);
        return appPath;
    }

    private static void ExtractResource(string resourceName, string targetPath)
    {
        using Stream? input = Assembly.GetExecutingAssembly().GetManifestResourceStream(resourceName);
        if (input is null)
        {
            throw new InvalidOperationException("Missing installer resource: " + resourceName);
        }

        using FileStream output = File.Create(targetPath);
        input.CopyTo(output);
    }

    private static void CreateShortcut(string shortcutPath, string targetPath, string iconPath)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(shortcutPath)!);

        Type? shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType is null)
        {
            return;
        }

        dynamic shell = Activator.CreateInstance(shellType)!;
        dynamic shortcut = shell.CreateShortcut(shortcutPath);
        shortcut.TargetPath = targetPath;
        shortcut.WorkingDirectory = Path.GetDirectoryName(targetPath);
        shortcut.IconLocation = iconPath;
        shortcut.Description = AppName;
        shortcut.Save();
    }

    private static void RegisterUninstaller(string installDir, string appPath, string uninstallPath)
    {
        using RegistryKey key = Registry.CurrentUser.CreateSubKey(
            @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + AppId);

        key.SetValue("DisplayName", AppName, RegistryValueKind.String);
        key.SetValue("DisplayVersion", "1.0.0", RegistryValueKind.String);
        key.SetValue("Publisher", "Data Receive and Analysis", RegistryValueKind.String);
        key.SetValue("InstallLocation", installDir, RegistryValueKind.String);
        key.SetValue("DisplayIcon", appPath, RegistryValueKind.String);
        key.SetValue(
            "UninstallString",
            $"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"{uninstallPath}\"",
            RegistryValueKind.String);
        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        key.SetValue("EstimatedSize", DirectorySizeInKb(installDir), RegistryValueKind.DWord);
    }

    private static int DirectorySizeInKb(string directory)
    {
        long bytes = Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories)
            .Sum(file => new FileInfo(file).Length);
        return (int)Math.Max(1, bytes / 1024);
    }

    private static string BuildUninstallScript()
    {
        return """
        $ErrorActionPreference = 'SilentlyContinue'
        $installDir = Split-Path -Parent $PSCommandPath
        $appName = 'Data Receive and Analysis'
        $appId = 'DataReceiveAndAnalysis'

        $desktopShortcut = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) ($appName + '.lnk')
        Remove-Item -LiteralPath $desktopShortcut -Force

        $startMenuDir = Join-Path ([Environment]::GetFolderPath('Programs')) $appName
        Remove-Item -LiteralPath $startMenuDir -Recurse -Force

        Remove-Item -LiteralPath ('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\' + $appId) -Recurse -Force

        Start-Process -FilePath $env:ComSpec -ArgumentList "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$installDir`"" -WindowStyle Hidden
        """;
    }
}
