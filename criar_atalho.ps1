$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (& python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))").Trim()
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\ConfereVideo.lnk')
$lnk.TargetPath = $py
$lnk.Arguments = '"' + (Join-Path $dir 'app.py') + '"'
$lnk.WorkingDirectory = $dir
$lnk.IconLocation = (Join-Path $dir 'icone.ico')
$lnk.Description = 'ConfereVideo - conferencia da separacao por video'
$lnk.Save()
Write-Host "Atalho criado."
