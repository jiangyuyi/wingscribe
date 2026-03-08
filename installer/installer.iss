; WingScribe CPU Installer Script
; Version for systems without NVIDIA GPU

#define AppName "WingScribe"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "WingScribe Project"
#define AppExeName "start_web.bat"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userdocs}\WingScribe
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=WingScribe-Setup-CPU-{#AppVersion}
Compression=lzma2
SolidCompression=yes
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
; Embedded Python runtime with pre-installed packages (CPU version)
Source: "build-cpu\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; WingScribe source code
Source: "build-cpu\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build-cpu\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build-cpu\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; IOC bird reference data (required for species recognition)
Source: "build-cpu\data\references\*"; DestDir: "{app}\data\references"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Tools
Source: "tools\exiftool.exe"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: main
Source: "tools\exiftool_files\*"; DestDir: "{app}\tools\exiftool_files"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Documentation
Source: "build-cpu\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-cpu\CLAUDE.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-cpu\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main

[Files]
; YOLO model files
Source: "build-cpu\data\models\*"; DestDir: "{app}\data\models"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Create data directories
Name: "{app}\data"
Name: "{app}\data\db"
Name: "{app}\data\models"
Name: "{app}\data\processed"
Name: "{app}\data\references"

[Icons]
; Start menu
Name: "{group}\WingScribe"; Filename: "{app}\scripts\start_web.bat"; WorkingDir: {app}
Name: "{group}\Configuration Guide"; Filename: "{app}\scripts\start_web.bat"; Parameters: "--config-guide"; WorkingDir: {app}
Name: "{group}\Uninstall WingScribe"; Filename: "{uninstallexe}"

; Desktop shortcut
Name: "{autodesktop}\WingScribe"; Filename: "{app}\scripts\start_web.bat"; WorkingDir: {app}; Tasks: desktop

[Run]
; Launch web server after installation
; User will be directed to the web-based configuration page on first visit
Filename: "{app}\scripts\start_web.bat"; Description: "Launch WingScribe Web Service"; StatusMsg: "Starting Web service..."; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Delete all application files and user data
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\data"

