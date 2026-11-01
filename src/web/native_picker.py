"""Windows path picker without a dependency on embedded Python's Tk support."""
import base64
import json
import os
from pathlib import Path
import subprocess


SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$options=[Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
if($options.kind -eq 'folder') {
 $dialog=New-Object System.Windows.Forms.FolderBrowserDialog
 $dialog.Description=$options.title
 $dialog.SelectedPath=$options.initial
} else {
 $dialog=New-Object System.Windows.Forms.OpenFileDialog
 $dialog.Title=$options.title
 $dialog.CheckFileExists=$true
 if(Test-Path -LiteralPath $options.initial -PathType Container){
  $dialog.InitialDirectory=$options.initial
 } elseif($options.initial) {
  $dialog.InitialDirectory=[IO.Path]::GetDirectoryName($options.initial)
  $dialog.FileName=[IO.Path]::GetFileName($options.initial)
 }
 $filters=@()
 foreach($extension in ($options.types -split '\|')) {
  if($extension -match '^[a-zA-Z0-9]+$'){$filters+= "$extension files (*.$extension)|*.$extension"}
 }
 $filters+='All files (*.*)|*.*'
 $dialog.Filter=$filters -join '|'
}
try {
 $selected=$null
 if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){
  if($options.kind -eq 'folder'){$selected=$dialog.SelectedPath}else{$selected=$dialog.FileName}
 }
 @{path=$selected} | ConvertTo-Json -Compress
} finally {$dialog.Dispose()}
'''


def choose_path(kind: str, title: str, initial: str = '', types: str = '') -> str | None:
    """Return a selected local/UNC path, or None on explicit cancellation."""
    if kind not in ('folder', 'file'):
        raise ValueError('Unsupported picker kind')
    if initial:
        initial = str(Path(initial).absolute())
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run(
        [str(executable), '-NoProfile', '-STA', '-EncodedCommand',
         base64.b64encode(SCRIPT.encode('utf-16le')).decode('ascii')],
        input=json.dumps(dict(kind=kind, title=title, initial=initial, types=types)).encode('utf-8'),
        capture_output=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    if result.returncode:
        raise RuntimeError('无法打开 Windows 路径选择窗口，请确认应用运行在已登录的桌面会话中。')
    try:
        path = json.loads(result.stdout.decode('utf-8-sig'))['path']
        if path is not None and not isinstance(path, str):
            raise ValueError('Invalid picker result')
        return path
    except (ValueError, KeyError) as exc:
        raise RuntimeError('路径选择窗口返回了无效结果，请重试。') from exc
