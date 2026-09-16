Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
stateDir = projectRoot & "\state"
If Not fso.FolderExists(stateDir) Then fso.CreateFolder(stateDir)
launcherLog = stateDir & "\origenerator_launcher.log"

Function Quote(s)
  Quote = Chr(34) & s & Chr(34)
End Function

Sub AppendLog(msg)
  On Error Resume Next
  Dim ts
  Set ts = fso.OpenTextFile(launcherLog, 8, True)
  ts.WriteLine Now & " " & msg
  ts.Close
End Sub

Function FindPythonCommand()
  Dim venvPython

  ' The copy a previous run left named for this app, then the plain venv
  ' interpreter.  Windows identifies a process by the file it was started from,
  ' so a plain python.exe arrives as one more anonymous "Python" among every
  ' other Python app on the machine; app_support.process_identity makes a copy
  ' that says Origenerator instead.  The run makes it for the run after, so a
  ' checkout that has never started launches exactly as it used to.
  namedPython = projectRoot & "\.venv\Scripts\Origenerator-Origenerator.exe"
  If fso.FileExists(namedPython) Then
    FindPythonCommand = Quote(namedPython)
    Exit Function
  End If

  venvPython = projectRoot & "\.venv\Scripts\python.exe"
  If fso.FileExists(venvPython) Then
    FindPythonCommand = Quote(venvPython)
    Exit Function
  End If
  FindPythonCommand = ""
End Function

pythonCmd = FindPythonCommand()
If pythonCmd = "" Then
  AppendLog "ERROR: Origenerator's install is missing: " & projectRoot & "\.venv"
  MsgBox "Origenerator's install is missing:" & vbCrLf & projectRoot & "\.venv", vbCritical, "Origenerator"
  WScript.Quit 1
End If

cmd = "cmd /c cd /d " & Quote(projectRoot) & " && " & pythonCmd & " -m origenerator 1>>" & Quote(launcherLog) & " 2>&1"
AppendLog "INFO: Launching with command: " & cmd
shell.Run cmd, 0, False
