#ifndef StageDir
  #error StageDir must identify a staged, verified Docker Desktop installer directory
#endif
#ifndef OutputDir
  #error OutputDir must identify the installer output directory
#endif
#include StageDir + "\docker-version.iss"

[Setup]
AppId={{B186C985-BC52-490A-ABE0-43F2F577C312}
AppName=NIPAT (Docker Desktop)
AppVersion={#NipatVersion}
SetupMutex=NIPAT-DockerDesktop-Setup-B186C985-BC52-490A-ABE0-43F2F577C312
AppPublisher=NIPAT contributors
AppPublisherURL=https://github.com/GregorioDalia/nipat-desktop
LicenseFile={#StageDir}\app\LICENSE
DefaultDirName={localappdata}\Programs\NIPAT-DockerDesktop
DisableDirPage=yes
DefaultGroupName=NIPAT (Docker Desktop)
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
OutputDir={#OutputDir}
OutputBaseFilename=NIPAT-DockerDesktop-Setup
Compression=lzma2
SolidCompression=yes
DiskSpanning=no
WizardStyle=modern
UninstallDisplayName=NIPAT (Docker Desktop) {#NipatVersion}
CloseApplications=yes
RestartApplications=no

[Files]
; Every source has an expected hash; the scientific archive is stored unchanged.
#include StageDir + "\docker-files.iss"

[Dirs]
; User inputs and results are independent of the installed application.
Name: "{localappdata}\NIPAT-DockerDesktop\data"; Flags: uninsneveruninstall
Name: "{localappdata}\NIPAT-DockerDesktop\runs"; Flags: uninsneveruninstall

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento NIPAT (Docker Desktop) sul desktop"

[Icons]
Name: "{autodesktop}\NIPAT (Docker Desktop)"; Filename: "{app}\NIPAT.exe"; WorkingDir: "{localappdata}\NIPAT-DockerDesktop\data"; Tasks: desktopicon
Name: "{group}\NIPAT (Docker Desktop)"; Filename: "{app}\NIPAT.exe"; WorkingDir: "{localappdata}\NIPAT-DockerDesktop\data"
Name: "{group}\Guida NIPAT"; Filename: "{app}\docs\GUIDA_UTILIZZO.md"
Name: "{group}\Disinstalla NIPAT (Docker Desktop)"; Filename: "{uninstallexe}"

[Code]
var
  PreparationResult: Integer;

function InitializeSetup(): Boolean;
begin
  Result := not IsAdmin;
  if not Result then
    MsgBox('Avvia NIPAT-DockerDesktop-Setup.exe normalmente, senza "Esegui come amministratore". ' +
      'NIPAT viene installato solo per il tuo utente Windows.', mbError, MB_OK);
end;

function QuoteNipatArgument(Value: String): String;
var
  I, J, Backslashes: Integer;
begin
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
  Parameters: String;
  Started: Boolean;
begin
  if CurStep = ssPostInstall then begin
    Parameters := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' +
      QuoteNipatArgument(ExpandConstant('{app}\scripts\windows\setup.ps1'));
    Started := ExecAsOriginalUser(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, PreparationResult);
    if not Started then PreparationResult := 1;
    if PreparationResult <> 0 then
      MsgBox('NIPAT e'' installato. Per completare la preparazione, avvia Docker Desktop ' +
        'in modalita'' Linux e apri l''icona "NIPAT (Docker Desktop)". ' +
        'La preparazione riprendera'' automaticamente.', mbInformation, MB_OK);
  end;
end;

function GetCustomSetupExitCode(): Integer;
begin
  Result := 0;
  if PreparationResult <> 0 then Result := 1;
end;

{ No uninstall command stops Docker, removes images or deletes user data/results. }
