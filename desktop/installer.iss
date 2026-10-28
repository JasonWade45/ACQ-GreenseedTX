; Inno Setup script — the double-click installer for Acquisitions Assistant.
;
; Built by scripts/build_windows.py, which passes /DAppVersion= and /DSourceExe=.
; Installs per user (no administrator prompt, no UAC) so it can go on any PC.
;
; Your data is NOT inside the program folder: the app writes to
;   %LOCALAPPDATA%\AcquisitionsAssistant
; so upgrading, repairing or uninstalling never touches the database. Removing the
; program asks first and keeps the data unless you say otherwise.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceExe
  #define SourceExe "..\dist\ACQ.exe"
#endif

#define AppName "Acquisitions Assistant"
#define AppPublisher "GreenSeedTX LLC"
#define AppFolder "AcquisitionsAssistant"

[Setup]
AppId={{B4F2C1A9-3D7E-4E6B-9C15-8A2D6F0E1001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppFolder}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=ACQ-Setup-{#AppVersion}
SetupIconFile=acq.ico
UninstallDisplayIcon={app}\ACQ.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a shortcut on the Desktop"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Acquisitions Assistant automatically when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ACQ.exe"; IconFilename: "{app}\ACQ.exe"
Name: "{group}\Open data folder"; Filename: "{localappdata}\{#AppFolder}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ACQ.exe"; IconFilename: "{app}\ACQ.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "AcquisitionsAssistant"; ValueData: """{app}\ACQ.exe"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\ACQ.exe"; Description: "Open Acquisitions Assistant now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only files this installer created. Your database, .env and backups stay.
Type: filesandordirs; Name: "{app}"

[Code]
var
  KeepData: Boolean;

function DataFolderNotEmpty(): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(ExpandConstant('{localappdata}\{#AppFolder}\data\*.db'), FindRec) then
  begin
    Result := True;
    FindClose(FindRec);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if DataFolderNotEmpty() then
    begin
      KeepData := MsgBox('Your seller database, password and backups are still in:' + #13#10 +
        ExpandConstant('{localappdata}\{#AppFolder}') + #13#10#13#10 +
        'Keep them so a future version opens with all your sellers?',
        mbConfirmation, MB_YESNO) = IDYES;
      if not KeepData then
        DelTree(ExpandConstant('{localappdata}\{#AppFolder}'), True, True, True);
    end;
  end;
end;
