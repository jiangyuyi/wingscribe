// Shared prerequisite gate for both variants. Main app remains per-user.
function HasVCRuntime: Boolean;
var
  Installed, Major, Minor, Build, Revision: Cardinal;
  Key: String;
begin
  Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  Result := False;
  if not IsWin64 then exit;
  if not RegQueryDWordValue(HKLM64, Key, 'Installed', Installed) then exit;
  if Installed <> 1 then exit;
  if not RegQueryDWordValue(HKLM64, Key, 'Major', Major) then exit;
  if not RegQueryDWordValue(HKLM64, Key, 'Minor', Minor) then exit;
  if not RegQueryDWordValue(HKLM64, Key, 'Bld', Build) then exit;
  if not RegQueryDWordValue(HKLM64, Key, 'Rbld', Revision) then exit;
  Result := (Major = 14) and ((Minor > 51) or
    ((Minor = 51) and (Build >= 36247)));
end;

function PrepareVCRuntime(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  PackagePath: String;
begin
  Result := '';
  if HasVCRuntime then exit;
  Result := 'Microsoft Visual C++ x64 runtime 14.51.36247 or newer v14 is required. Install the Microsoft runtime, then run WingScribe Setup again.';
  if WizardSilent then exit;
  if MsgBox('WingScribe needs the Microsoft Visual C++ x64 runtime. Setup will open its installer. Complete the license/admin prompts and CLOSE its completion window to continue. No automatic restart will be requested. Continue?', mbConfirmation, MB_YESNO) <> IDYES then exit;
  ExtractTemporaryFile('vc_redist.x64.exe');
  PackagePath := ExpandConstant('{tmp}\vc_redist.x64.exe');
  if CompareText(GetSHA256OfFile(PackagePath), '843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c') <> 0 then begin
    Result := 'Bundled Microsoft runtime hash mismatch. Installation stopped.';
    exit;
  end;
  WizardForm.StatusLabel.Caption := 'Waiting for Microsoft runtime installer: close its completion window to continue.';
  if not ShellExec('runas', PackagePath, '/install /norestart', '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then begin
    Result := 'Microsoft runtime installer could not start or administrator permission was cancelled. No WingScribe files were installed.';
    exit;
  end;
  if (Code = 3010) or (Code = 1641) then begin
    NeedsRestart := True;
    Result := 'Microsoft runtime requires a Windows restart. Restart when convenient, then run WingScribe Setup again.';
    exit;
  end;
  if Code <> 0 then begin
    Result := Format('Microsoft runtime installation failed (exit %d). Resolve it before installing WingScribe.', [Code]);
    exit;
  end;
  if HasVCRuntime then Result := '';
end;
