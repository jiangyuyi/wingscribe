; WingScribe Installer Script
; Simplified version for testing

#define AppName "WingScribe"
#define AppVersion "1.0.0"
#define AppPublisher "WingScribe Project"
#define AppExeName "start_web.bat"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userdocs}\WingScribe
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=WingScribe-Setup-{#AppVersion}
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
; Virtual environment with pre-installed packages
Source: "build\venv\*"; DestDir: "{app}\venv"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; WingScribe source code
Source: "build\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "build\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Tools
Source: "tools\exiftool.exe"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: main

; Documentation
Source: "build\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build\CLAUDE.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "build\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main

[Dirs]
; Create data directories
Name: "{app}\data"
Name: "{app}\data\db"
Name: "{app}\data\models"
Name: "{app}\data\processed"
Name: "{app}\data\references"

[Icons]
; Start menu
Name: "{group}\WingScribe"; Filename: "{app}\scripts\start_web.bat"
Name: "{group}\Config Wizard"; Filename: "{app}\venv\Scripts\python.exe"; Parameters: """{app}\scripts\config_wizard.py"""
Name: "{group}\Uninstall WingScribe"; Filename: "{uninstallexe}"

; Desktop shortcut
Name: "{autodesktop}\WingScribe"; Filename: "{app}\scripts\start_web.bat"; Tasks: desktop

[Run]
; Launch configuration wizard on first run (visible, wait for completion)
Filename: "{app}\venv\Scripts\python.exe"; Parameters: """{app}\scripts\config_wizard.py"""; Description: "Run configuration wizard"; StatusMsg: "Starting configuration wizard..."; Flags: waituntilterminated

; Launch web server if user chooses
Filename: "{app}\scripts\start_web.bat"; Description: "Launch WingScribe Web Service"; StatusMsg: "Starting Web service..."; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Delete all application files and user data
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\data"
