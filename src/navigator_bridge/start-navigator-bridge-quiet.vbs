Option Explicit
Dim fso, shell, folder, launcher, result, logRoot, logFile
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(folder, "start-navigator-bridge-quiet.cmd")
If Not fso.FileExists(launcher) Then
    MsgBox "Navigator Bridge startup file was not found: " & launcher, vbExclamation, "Navigator Bridge for FH6"
    WScript.Quit 2
End If
shell.CurrentDirectory = folder
' 0: suppress the console for this optional launcher only; True: report the real exit status.
result = shell.Run(Chr(34) & launcher & Chr(34), 0, True)
If result <> 0 Then
    logRoot = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
    If logRoot = "%LOCALAPPDATA%" Then
        logRoot = shell.ExpandEnvironmentStrings("%TEMP%") & "\Navigator-Bridge-for-FH6"
    Else
        logRoot = logRoot & "\Navigator-Bridge-for-FH6"
    End If
    logFile = logRoot & "\navigator-bridge-quiet-startup.log"
    MsgBox "Navigator Bridge did not start or exited with an error." & vbCrLf & _
           "Exit code: " & CStr(result) & vbCrLf & _
           "Log: " & logFile & vbCrLf & _
           "The original navigator-bridge-for-fh6.py is still available.", vbExclamation, "Navigator Bridge for FH6"
End If
WScript.Quit result
