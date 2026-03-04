[Setup]
AppName=WingScribe Test
AppVersion=1.0
DefaultDirName={userdocs}\WingScribe
OutputDir=Output
OutputBaseFilename=test-setup

[Files]
Source: "build\scripts\start_web.bat"; DestDir: "{app}\scripts"
