#ifndef StageDir
  #error StageDir must identify a staged, verified installer directory
#endif
#ifndef RuntimeAssetsDir
  #error RuntimeAssetsDir must identify the two verified runtime archives
#endif
#ifndef OutputDir
  #define OutputDir "..\..\build\output"
#endif
#define NipatVersion "0.4.1"

[Setup]
AppId={{5C0FD852-ED53-4F4B-92D2-64B784E7F9B3}
AppName=NIPAT
AppVersion={#NipatVersion}
AppPublisher=NIPAT contributors
AppPublisherURL=https://github.com/GregorioDalia/nipat-desktop
LicenseFile={#StageDir}\app\LICENSE
DefaultDirName={localappdata}\Programs\NIPAT
DisableDirPage=yes
DefaultGroupName=NIPAT
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
OutputDir={#OutputDir}
OutputBaseFilename=NIPAT-Setup
Compression=lzma2
SolidCompression=yes
DiskSpanning=no
WizardStyle=modern
UninstallDisplayName=NIPAT {#NipatVersion}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#StageDir}\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The archives are embedded and written once, directly into the verified resume cache.
#include StageDir + "\runtime-assets.iss"

[Dirs]
; Shortcuts have a valid working directory even before WSL setup/reboot completes.
Name: "{localappdata}\NIPAT\data"; Flags: uninsneveruninstall
Name: "{localappdata}\NIPAT\runs"; Flags: uninsneveruninstall

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento NIPAT sul desktop"

[Icons]
Name: "{autodesktop}\NIPAT"; Filename: "{app}\NIPAT.exe"; WorkingDir: "{localappdata}\NIPAT\data"; Tasks: desktopicon
Name: "{group}\NIPAT"; Filename: "{app}\NIPAT.exe"; WorkingDir: "{localappdata}\NIPAT\data"
Name: "{group}\NIPAT - completa preparazione"; Filename: "{app}\1_SETUP.cmd"; WorkingDir: "{app}"
Name: "{group}\Guida NIPAT"; Filename: "{app}\docs\GUIDA_UTILIZZO.md"
Name: "{group}\Disinstalla NIPAT"; Filename: "{uninstallexe}"

[Code]
var
  BootstrapResult: Integer;
  WslRebootRequired: Boolean;

function InitializeSetup(): Boolean;
begin
  Result := not IsAdmin;
  if not Result then
    MsgBox('Avvia NIPAT-Setup.exe normalmente, senza "Esegui come amministratore". ' +
      'Solo il componente che abilita WSL chiedera'' l''autorizzazione UAC. ' +
      'Applicazione e distribuzione Linux appartengono al tuo utente Windows.', mbError, MB_OK);
end;

function QuoteNipatArgument(Value: String): String;
var
  I, J, Backslashes: Integer;
begin
  { Windows argv quoting: backslashes before quotes and at the end are doubled. }
  Result := '"';
  Backslashes := 0;
  for I := 1 to Length(Value) do begin
    if Value[I] = '\' then
      Backslashes := Backslashes + 1
    else begin
      if Value[I] = '"' then begin
        for J := 1 to (Backslashes * 2 + 1) do Result := Result + '\';
      end else begin
        for J := 1 to Backslashes do Result := Result + '\';
      end;
      Result := Result + Value[I];
      Backslashes := 0;
    end;
  end;
  for J := 1 to (Backslashes * 2) do Result := Result + '\';
  Result := Result + '"';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AssetDir, Parameters: String;
  Started: Boolean;
begin
  if CurStep = ssPostInstall then begin
    AssetDir := ExpandConstant('{param:ASSETDIR|}');
    Parameters := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' +
      QuoteNipatArgument(ExpandConstant('{app}\installer\windows\bootstrap.ps1'));
    if AssetDir <> '' then
      Parameters := Parameters + ' -AssetDirectory ' + QuoteNipatArgument(AssetDir);
    Started := ExecAsOriginalUser(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, BootstrapResult);
    if not Started then BootstrapResult := 1;
    WslRebootRequired := BootstrapResult = 3010;
    if (BootstrapResult <> 0) and not WslRebootRequired then
      MsgBox('I file NIPAT sono installati, ma la preparazione non e'' completata. ' +
        'Apri "NIPAT - completa preparazione" dal menu Start. ' +
        'Dettagli nel file .runtime\installer\setup.log della cartella NIPAT.', mbError, MB_OK);
  end;
end;

function NeedRestart(): Boolean;
begin
  Result := WslRebootRequired;
end;

function GetCustomSetupExitCode(): Integer;
begin
  Result := 0;
  if (BootstrapResult <> 0) and not WslRebootRequired then Result := 1;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce', 'NIPAT-ResumeSetup');
end;
