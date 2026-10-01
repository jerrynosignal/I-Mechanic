#define MyAppName "I, Mechanic"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "I, Mechanic contributors"
#define MyAppExeName "I Mechanic.exe"

[Setup]
AppId={{B6F8C3D2-0BD5-4D57-9D9A-8DDBB4AF0A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\I Mechanic
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=I-Mechanic-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

[Files]
Source: "..\dist\I Mechanic\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
