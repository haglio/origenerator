' Launch THIS WORKTREE's origenerator as a branch session, for judging a branch
' before it lands. Same shape as launch_origenerator.vbs, with the three things
' a worktree needs done differently:
'   - it borrows the primary checkout's .venv (a worktree has none of its own;
'     the primary is three levels up: <primary>\.claude\worktrees\<name>),
'     falling back to python on PATH exactly as the live launcher does — the
'     primary runs happily without a venv, and a preview that refuses to start
'     where the live app starts fine is a review cycle lost to the launcher,
'   - it marks the run a branch session (ORIGENERATOR_BRANCH_SESSION=1), so the
'     app seeds its database from the primary's and skips the library
'     maintenance only the live app should do (see origenerator/branch_session.py),
'   - state (DB, thumbnails, trash) stays in the worktree's own state\ folder,
'     so the live install's state is untouched.
' Close the live app first — two instances would both drive ComfyUI. Copy the
' primary's content.local.json into the worktree root before the first run, or
' the session comes up on the example overlay and finds no library.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
stateDir = projectRoot & "\state"
If Not fso.FolderExists(stateDir) Then fso.CreateFolder(stateDir)
launcherLog = stateDir & "\origenerator_launcher.log"

Function Quote(s)
  Quote = Chr(34) & s & Chr(34)
End Function

' <primary>\.claude\worktrees\<this worktree> -> up three levels to the primary.
primaryRoot = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(projectRoot)))

' The primary's venv when it has one, else whatever python the live launcher
' would have found. An empty or absent .venv is a normal state of the primary
' (it runs off PATH python), so refusing to launch there would strand every
' preview behind a MsgBox for an interpreter the app never needed.
Function FindPythonCommand()
  Dim venvPython, candidates, i

  venvPython = primaryRoot & "\.venv\Scripts\python.exe"
  If fso.FileExists(venvPython) Then
    FindPythonCommand = Quote(venvPython)
    Exit Function
  End If

  candidates = Array( _
    "python", _
    "py -3" _
  )
  For i = 0 To UBound(candidates)
    If shell.Run("cmd /c where " & Split(candidates(i), " ")(0) & " >nul 2>nul", 0, True) = 0 Then
      FindPythonCommand = candidates(i)
      Exit Function
    End If
  Next
  FindPythonCommand = ""
End Function

pythonCmd = FindPythonCommand()
If pythonCmd = "" Then
  MsgBox "Could not find python or py launcher.", vbCritical, "Origenerator (branch preview)"
  WScript.Quit 1
End If

parentDir = fso.GetParentFolderName(primaryRoot)
cmd = "cmd /c cd /d " & Quote(projectRoot) & " && set PYTHONPATH=" & parentDir & "&&set ORIGENERATOR_BRANCH_SESSION=1&&" & pythonCmd & " -m origenerator 1>>" & Quote(launcherLog) & " 2>&1"
shell.Run cmd, 0, False
