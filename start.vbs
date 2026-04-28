' Launch WhisperWriter with admin elevation.
' Self-elevates via UAC if not already elevated, then runs pythonw + main.py
' silently. All paths are derived from the script's own location, so the
' project can be moved without breaking the launcher.

Const SW_HIDE = 0

' Self-elevation: if the /elevated flag isn't already passed, re-launch
' ourselves through the "runas" ShellExecute verb (which triggers a UAC
' prompt). The elevated copy enters this script with the flag set and
' falls through to the actual launch.
If WScript.Arguments.Named.Exists("elevated") = False Then
    Set shellApp = CreateObject("Shell.Application")
    shellApp.ShellExecute "wscript.exe", _
        """" & WScript.ScriptFullName & """ /elevated", _
        "", "runas", SW_HIDE
    WScript.Quit
End If

' Now running elevated. Build paths and start pythonw.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw   = fso.BuildPath(scriptDir, "venv\Scripts\pythonw.exe")
mainPy    = fso.BuildPath(scriptDir, "src\main.py")

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = scriptDir
sh.Run """" & pythonw & """ """ & mainPy & """", SW_HIDE, False
