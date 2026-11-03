function DirectoryProbeTick: Cardinal;
  external 'GetTickCount@kernel32.dll stdcall';

// Check using the same user token that will run the installed application.
function CheckInstallDirectory: String;
var
  Directory, Parent, Probe: String;
  Attempt: Integer;
  Created: Boolean;
begin
  Result := '';
  Directory := ExpandConstant('{app}');
  while not DirExists(Directory) do begin
    if FileExists(Directory) then begin
      Result := 'The selected installation path contains an existing file.';
      exit;
    end;
    Parent := ExtractFileDir(RemoveBackslashUnlessRoot(Directory));
    if (Parent = '') or (Parent = Directory) then begin
      Result := 'The selected installation drive or folder is unavailable.';
      exit;
    end;
    Directory := Parent;
  end;
  Created := False;
  for Attempt := 1 to 20 do begin
    Probe := AddBackslash(Directory) + '.wingscribe-write-test-' +
      IntToStr(DirectoryProbeTick) + '-' + IntToStr(Attempt);
    if not DirExists(Probe) and not FileExists(Probe) then
      if CreateDir(Probe) then begin
        Created := True;
        break;
      end;
  end;
  if not Created then
    Result := 'WingScribe needs a folder writable by your Windows account. ' +
      'The selected folder or its parent cannot be written to: ' + Directory + #13#10#13#10 +
      'Choose the default folder under your Documents, or another writable folder. ' +
      'Program Files normally requires administrator permission. WingScribe also saves configuration and data in its installation folder.'
  else if not RemoveDir(Probe) then
    Result := 'Could not remove the installation write-test folder: ' + Probe;

end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: String;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not WizardSilent then begin
    Error := CheckInstallDirectory;
    if Error <> '' then begin
      MsgBox(Error, mbError, MB_OK);
      Result := False;
    end;
  end;
end;
