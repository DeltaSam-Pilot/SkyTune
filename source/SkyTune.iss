; Per-user installer. It does not ask for administrator rights.
; Uninstall removes only the program folder. Settings backups and Community packages are not deleted.
#define MyAppName "SkyTune"
#define MyAppVersion "1.8.1"

[Setup]
AppId={{8F4C2A91-6B17-4E5A-9D33-7A1E0C5B2D44}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\SkyTune
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=installer-out
OutputBaseFilename=SkyTune-1.8.1-setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\SkyTune.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\SkyTune.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SkyTune"; Filename: "{app}\SkyTune.exe"
Name: "{autodesktop}\SkyTune"; Filename: "{app}\SkyTune.exe"
