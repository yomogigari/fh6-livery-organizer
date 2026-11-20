Option Explicit
Dim fso, shell, folder, launcher, result, logRoot, logFile
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(folder, "start-viewer-gui-quiet.cmd")
If Not fso.FileExists(launcher) Then
    MsgBox "Viewer startup file was not found: " & launcher, vbExclamation, "Livery Organizer for FH6"
    WScript.Quit 2
End If
shell.CurrentDirectory = folder
' 0: suppress the console for this optional launcher only; True: report the real exit status.
result = shell.Run(Chr(34) & launcher & Chr(34), 0, True)
If result <> 0 Then
    logRoot = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
    If logRoot = "%LOCALAPPDATA%" Then
        logRoot = shell.ExpandEnvironmentStrings("%TEMP%") & "\LO4FH6"
    Else
        logRoot = logRoot & "\Livery Organizer for FH6\PreviewBridge"
    End If
    logFile = logRoot & "\viewer-gui-quiet-startup.log"
    MsgBox "Viewer did not start or exited with an error." & vbCrLf & _
           "Exit code: " & CStr(result) & vbCrLf & _
           "Log: " & logFile & vbCrLf & _
           "The original start-viewer-gui.cmd is still available.", vbExclamation, "Livery Organizer for FH6"
End If
WScript.Quit result
