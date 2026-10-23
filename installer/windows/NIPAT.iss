#ifndef StageDir
  #error StageDir must identify a staged, verified installer directory
#endif
#ifndef RuntimeAssetsDir
  #error RuntimeAssetsDir must identify the two verified runtime archives
#endif
#ifndef OutputDir
  #define OutputDir "..\..\build\output"
#endif
#include StageDir + "\install-profile.iss"

[Setup]
AppId={#NipatAppId}
AppName={#NipatDisplayName}
AppVersion={#NipatVersion}
AppPublisher=NIPAT contributors
AppPublisherURL=https://github.com/GregorioDalia/nipat-desktop
LicenseFile={#StageDir}\app\LICENSE
DefaultDirName={localappdata}\Programs\{#NipatAppDirectory}
DisableDirPage=yes
UsePreviousAppDir=no
DefaultGroupName={#NipatDisplayName}
UsePreviousGroup=no
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
UninstallDisplayName={#NipatDisplayName} {#NipatVersion}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#StageDir}\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The archives are embedded and written once, directly into the verified resume cache.
#include StageDir + "\runtime-assets.iss"

[Dirs]
; Shortcuts have a valid working directory even before WSL setup/reboot completes.
Name: "{localappdata}\{#NipatDataDirectory}\data"; Flags: uninsneveruninstall
Name: "{localappdata}\{#NipatDataDirectory}\runs"; Flags: uninsneveruninstall

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento {#NipatDisplayName} sul desktop"

[Icons]
Name: "{autodesktop}\{#NipatDisplayName}"; Filename: "{app}\NIPAT.exe"; WorkingDir: "{localappdata}\{#NipatDataDirectory}\data"; Tasks: desktopicon
Name: "{group}\{#NipatDisplayName}"; Filename: "{app}\NIPAT.exe"; WorkingDir: "{localappdata}\{#NipatDataDirectory}\data"
Name: "{group}\{#NipatDisplayName} - completa preparazione"; Filename: "{app}\1_SETUP.cmd"; WorkingDir: "{app}"
Name: "{group}\Guida {#NipatDisplayName}"; Filename: "{app}\docs\GUIDA_UTILIZZO.md"
Name: "{group}\Disinstalla {#NipatDisplayName}"; Filename: "{uninstallexe}"

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

function NipatPathHasReparsePoint(Path: String): Boolean;
var
  Parent: String;
  Entry: TFindRec;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(Path);
  while Path <> '' do begin
    if FindFirst(Path, Entry) then begin
      try
        Result := (Entry.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0;
      finally
        FindClose(Entry);
      end;
      if Result then Exit;
    end;
    Parent := ExtractFileDir(Path);
    if CompareText(Parent, Path) = 0 then Exit;
    Path := Parent;
  end;
end;

function NipatTreeHasReparsePoint(Path: String): Boolean;
var
  Entry: TFindRec;
begin
  Result := False;
  if not FindFirst(AddBackslash(Path) + '*', Entry) then Exit;
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
        if (Entry.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then begin
          Result := True;
          Exit;
        end;
        if (Entry.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          if NipatTreeHasReparsePoint(AddBackslash(Path) + Entry.Name) then begin
            Result := True;
            Exit;
          end;
      end;
    until not FindNext(Entry);
  finally
    FindClose(Entry);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExpectedApp, DataRoot: String;
begin
  Result := '';
  ExpectedApp := ExpandConstant('{localappdata}\Programs\{#NipatAppDirectory}');
  DataRoot := ExpandConstant('{localappdata}\{#NipatDataDirectory}');
  { /DIR and /GROUP still work with hidden wizard pages. Reject them before copying. }
  if (CompareText(RemoveBackslashUnlessRoot(ExpandConstant('{app}')), ExpectedApp) <> 0) or
     (CompareText(WizardGroupValue, '{#NipatDisplayName}') <> 0) then begin
    Result := 'Questa Preview richiede la propria cartella e il proprio gruppo Start. ' +
      'Riavviare il setup senza opzioni /DIR o /GROUP; NIPAT stabile resta separato.';
    Exit;
  end;
  if NipatPathHasReparsePoint(ExpectedApp) or NipatPathHasReparsePoint(DataRoot) or
     NipatTreeHasReparsePoint(ExpectedApp) or
     NipatPathHasReparsePoint(AddBackslash(DataRoot) + 'cache') or
     NipatTreeHasReparsePoint(AddBackslash(DataRoot) + 'cache') or
     NipatPathHasReparsePoint(AddBackslash(DataRoot) + 'data') or
     NipatPathHasReparsePoint(AddBackslash(DataRoot) + 'runs') then
    Result := 'Le cartelle della Preview contengono collegamenti o junction. ' +
      'Nessun file viene copiato: conservare le cartelle esistenti e contattare il supporto.';
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
        'Apri "{#NipatDisplayName} - completa preparazione" dal menu Start. ' +
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
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce', '{#NipatResumeKey}');
end;
