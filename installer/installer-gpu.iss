; WingScribe GPU Installer Script
; Version with CUDA support for NVIDIA GPUs

#define AppName "WingScribe"
#define AppVersion "1.0.0"
#define AppPublisher "WingScribe Project"
#define AppExeName "start_web.bat"

[Setup]
AppName={#AppName} (GPU)
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userdocs}\WingScribe-GPU
DefaultGroupName={#AppName} GPU
OutputDir=Output
OutputBaseFilename=WingScribe-Setup-GPU-{#AppVersion}
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
; Virtual environment with pre-installed packages (GPU version)
Source: "build-gpu\venv\*"; DestDir: "{app}\venv"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Embedded Python for venv creation on target machines
Source: "build-gpu\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; WingScribe source code
Source: "build-gpu\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build-gpu\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build-gpu\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; IOC bird reference data (required for species recognition)
Source: "build-gpu\data\references\*"; DestDir: "{app}\data\references"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Tools
Source: "tools\exiftool.exe"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: main

; Documentation
Source: "build-gpu\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-gpu\CLAUDE.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build-gpu\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main

[Files]
; YOLO model files
Source: "build-gpu\data\models\*"; DestDir: "{app}\data\models"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Create data directories
Name: "{app}\data"
Name: "{app}\data\db"
Name: "{app}\data\models"
Name: "{app}\data\processed"
Name: "{app}\data\references"

[Icons]
; Start menu
Name: "{group}\WingScribe GPU"; Filename: "{app}\scripts\start_web.bat"; WorkingDir: {app}
Name: "{group}\Configuration Guide"; Filename: "{app}\scripts\start_web.bat"; Parameters: "--config-guide"; WorkingDir: {app}
Name: "{group}\Uninstall WingScribe GPU"; Filename: "{uninstallexe}"

; Desktop shortcut
Name: "{autodesktop}\WingScribe GPU"; Filename: "{app}\scripts\start_web.bat"; WorkingDir: {app}; Tasks: desktop

[Run]
; Launch web server after installation
; User will be directed to the web-based configuration page on first visit
Filename: "{app}\scripts\start_web.bat"; Description: "Launch WingScribe Web Service (GPU)"; StatusMsg: "Starting Web service..."; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Delete all application files and user data
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\data"
