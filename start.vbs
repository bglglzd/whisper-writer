' Launch WhisperWriter silently (no console window).
' Uses the folder this script lives in, so the project can be moved
' without breaking the launcher.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

pythonw = fso.BuildPath(scriptDir, "venv\Scripts\pythonw.exe")
mainPy  = fso.BuildPath(scriptDir, "src\main.py")

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = scriptDir
sh.Run """" & pythonw & """ """ & mainPy & """", 0, False
