' Launch THIS WORKTREE's origenerator as a branch session, for judging a branch
' before it lands. Same shape as launch_origenerator.vbs, with the three things
' a worktree needs done differently:
'   - it borrows the primary checkout's .venv (a worktree has none of its own;
'     the primary is three levels up: <primary>\.claude\worktrees\<name>), and
'     with it the versions of the shared packages the app is pinned to,
'   - it marks the run a branch session (ORIGENERATOR_BRANCH_SESSION=1): the app
'     opens the live install's own library (the primary's database, thumbnails
'     and trash), so every generation shows in every instance, and leaves
'     ComfyUI's absence work to the live app (see origenerator/branch_session.py),
'   - only this window's own state (ui_state.json) and its logs land in the
'     worktree's state\ folder.
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

venvPython = primaryRoot & "\.venv\Scripts\python.exe"
If Not fso.FileExists(venvPython) Then
  MsgBox "Origenerator's install is missing:" & vbCrLf & primaryRoot & "\.venv", vbCritical, "Origenerator (branch preview)"
  WScript.Quit 1
End If

cmd = "cmd /c cd /d " & Quote(projectRoot) & " && set ORIGENERATOR_BRANCH_SESSION=1&&" & Quote(venvPython) & " -m origenerator 1>>" & Quote(launcherLog) & " 2>&1"
shell.Run cmd, 0, False
