; WingScribe CPU Installer Script
; Version for systems without NVIDIA GPU

#define AppName "WingScribe"
#ifndef AppVersion
  #define AppVersion "3.0.1"
#endif
#define AppPublisher "WingScribe Project"
#define AppExeName "start_web.bat"

[Setup]
#ifdef ValidationBuild
AppId=WingScribe-Isolated-cpu-B7c3
CreateUninstallRegKey=no
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userdocs}\WingScribe
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=WingScribe-Setup-CPU-{#AppVersion}
#ifdef ValidationBuild
Compression=none
SolidCompression=no
DiskSpanning=yes
#else
Compression=lzma2
SolidCompression=yes
#endif
AllowNoIcons=yes
CreateAppDir=yes
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "default"; Description: "Default installation"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "main"; Description: "Main program files"; Types: default custom; Flags: fixed
Name: "desktop"; Description: "Desktop shortcut"; Types: default

[Tasks]
Name: "desktop"; Description: "Create desktop shortcut"; GroupDescription: "Additional icons:"; Components: desktop

[Files]
Source: "build-cpu\prerequisites\vc_redist.x64.exe"; Flags: dontcopy
; Embedded Python runtime with pre-installed packages (CPU version)
Source: "build-cpu\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; WingScribe source code
Source: "build-cpu\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build-cpu\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build-cpu\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; IOC bird reference data (required for species recognition)
Source: "build-cpu\data\references\*"; DestDir: "{app}\data\references"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Tools
Source: "build-cpu\tools\exiftool.exe"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: main
Source: "build-cpu\tools\exiftool_files\*"; DestDir: "{app}\tools\exiftool_files"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Installation generation
Source: "build-cpu\installer-format.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main

; Documentation
Source: "build-cpu\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build-cpu\payload-manifest.json"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-cpu\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-cpu\uv.lock"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-cpu\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-cpu\CLAUDE.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-cpu\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main

[Files]
; YOLO model files
Source: "build-cpu\data\models\yolo26n.pt"; DestDir: "{app}\data\models"; Flags: ignoreversion

[Dirs]
; Create data directories
Name: "{app}\data"
Name: "{app}\data\db"
Name: "{app}\data\models"
Name: "{app}\data\processed"
Name: "{app}\data\references"

#ifndef ValidationBuild
[Icons]
; Start menu
Name: "{group}\WingScribe"; Filename: "{app}\scripts\start_web.bat"; WorkingDir: {app}; IconFilename: "{app}\src\web\static\favicon.ico"
Name: "{group}\Configuration Guide"; Filename: "{app}\scripts\start_web.bat"; Parameters: "--config-guide"; WorkingDir: {app}; IconFilename: "{app}\src\web\static\favicon.ico"
Name: "{group}\Uninstall WingScribe"; Filename: "{uninstallexe}"

; Desktop shortcut
Name: "{autodesktop}\WingScribe"; Filename: "{app}\scripts\start_web.bat"; WorkingDir: {app}; Tasks: desktop; IconFilename: "{app}\src\web\static\favicon.ico"

[Run]
; Launch web server after installation
; User will be directed to the web-based configuration page on first visit
Filename: "{app}\scripts\start_web.bat"; Description: "Launch WingScribe Web Service"; StatusMsg: "Starting Web service..."; Flags: nowait postinstall skipifsilent

#endif

; No recursive uninstall deletion: preserve application-created configuration,
; databases, backups and photographs. Inno removes its tracked payload only.
; Legacy upgrade/uninstall logs require separate validation before release.

[Code]
#include "vcredist.iss"
#include "install-directory.iss"
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Entry: TFindRec;
  Marker: AnsiString;
begin
  Result := '';
  if FindFirst(ExpandConstant('{app}\unins*.dat'), Entry) then begin
    FindClose(Entry);
    if (not LoadStringFromFile(ExpandConstant('{app}\installer-format.txt'), Marker)) or
       (Trim(String(Marker)) <> 'wingscribe-safe-v1') then
      Result := 'Legacy installation detected. Back up configuration and data, then choose a new empty installation directory. Do not run the old uninstaller before backing up your data.';
  end;
  if Result = '' then Result := CheckInstallDirectory;
  if Result = '' then Result := PrepareVCRuntime(NeedsRestart);
end;
