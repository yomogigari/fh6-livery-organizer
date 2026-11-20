using System;
using System.Diagnostics;
using System.IO;
using Microsoft.Win32;

internal static class LiveryOrganizerPreviewLauncher
{
    private const string SchemeKey = @"Software\Classes\liveryorganizerpreviewforfh6";

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args == null || args.Length < 1 || String.IsNullOrWhiteSpace(args[0]))
            {
                Log("ERROR: launch URI was not supplied.");
                return 2;
            }

            string pythonw;
            string bridgeScript;
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(SchemeKey, false))
            {
                if (key == null)
                {
                    Log("ERROR: URI registry key is missing.");
                    return 3;
                }
                pythonw = Convert.ToString(key.GetValue("PreviewPythonwPath"));
                bridgeScript = Convert.ToString(key.GetValue("PreviewBridgeScriptPath"));
            }

            if (String.IsNullOrWhiteSpace(pythonw) || !File.Exists(pythonw))
            {
                Log("ERROR: registered pythonw.exe is missing: " + pythonw);
                return 4;
            }
            if (String.IsNullOrWhiteSpace(bridgeScript) || !File.Exists(bridgeScript))
            {
                Log("ERROR: registered bridge script is missing: " + bridgeScript);
                return 5;
            }

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonw;
            psi.Arguments = Quote(bridgeScript) + " --uri " + Quote(args[0]) + " --gui-child";
            psi.WorkingDirectory = Path.GetDirectoryName(bridgeScript) ?? Environment.CurrentDirectory;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.ErrorDialog = false;
            Process.Start(psi);
            return 0;
        }
        catch (Exception ex)
        {
            Log("ERROR: " + ex.ToString());
            return 1;
        }
    }

    private static string Quote(string value)
    {
        if (value == null)
            return "\"\"";
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static void Log(string message)
    {
        try
        {
            string root = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Livery Organizer for FH6",
                "PreviewBridge"
            );
            Directory.CreateDirectory(root);
            string path = Path.Combine(root, "preview-native-launcher.log");
            File.AppendAllText(
                path,
                "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "] " + message + Environment.NewLine
            );
        }
        catch
        {
            // The launcher must never open a console or dialog for diagnostics.
        }
    }
}
