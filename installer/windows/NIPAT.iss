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
DefaultDirName={code:GetNipatDefaultAppDir}
DisableDirPage=no
UsePreviousAppDir=yes
SetupMutex=Local\NIPAT-Desktop-Installer
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
SetupIconFile={#StageDir}\app\assets\branding\nipat-icon.ico
UninstallDisplayName={#NipatDisplayName} {#NipatVersion}
UninstallDisplayIcon={app}\assets\branding\nipat-icon.ico
CloseApplications=yes
RestartApplications=no

[Files]
; Extract only these small files for shared validation before touching selected directories.
Source: "{#StageDir}\app\installer\windows\install-profile.ps1"; Flags: dontcopy noencryption
Source: "{#StageDir}\app\installer\windows\install-profile.json"; Flags: dontcopy noencryption
Source: "{#StageDir}\app\installer\windows\install-layout.ps1"; Flags: dontcopy noencryption
Source: "{#StageDir}\app\installer\windows\validate-install-layout.ps1"; Flags: dontcopy noencryption
Source: "{#StageDir}\app\installer\windows\repair-installation.ps1"; Flags: dontcopy noencryption
Source: "{#StageDir}\app\.distribution\application-files.json"; Flags: dontcopy noencryption
Source: "{#StageDir}\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The archives are embedded and written once, directly into the verified resume cache.
#include StageDir + "\runtime-assets.iss"

[Dirs]
; Shortcuts have a valid working directory even before WSL setup/reboot completes.
Name: "{code:GetNipatDataDir}"; Flags: uninsneveruninstall
Name: "{code:GetNipatRunsDir}"; Flags: uninsneveruninstall
Name: "{code:GetNipatRuntimeDir}"; Flags: uninsneveruninstall
Name: "{code:GetNipatCacheDir}"; Flags: uninsneveruninstall

[INI]
; Ownership markers persist so a later setup can reuse deliberately retained directories.
Filename: "{app}\.nipat-app.ini"; Section: "NIPAT"; Key: "schema_version"; String: "1"
Filename: "{app}\.nipat-app.ini"; Section: "NIPAT"; Key: "installation_channel"; String: "desktop"
Filename: "{app}\.nipat-app.ini"; Section: "NIPAT"; Key: "role"; String: "application"
Filename: "{code:GetNipatRuntimeDir}\.nipat-storage.ini"; Section: "NIPAT"; Key: "schema_version"; String: "1"
Filename: "{code:GetNipatRuntimeDir}\.nipat-storage.ini"; Section: "NIPAT"; Key: "installation_channel"; String: "desktop"
Filename: "{code:GetNipatRuntimeDir}\.nipat-storage.ini"; Section: "NIPAT"; Key: "role"; String: "runtime"
Filename: "{code:GetNipatCacheDir}\.nipat-storage.ini"; Section: "NIPAT"; Key: "schema_version"; String: "1"
Filename: "{code:GetNipatCacheDir}\.nipat-storage.ini"; Section: "NIPAT"; Key: "installation_channel"; String: "desktop"
Filename: "{code:GetNipatCacheDir}\.nipat-storage.ini"; Section: "NIPAT"; Key: "role"; String: "cache"

[Registry]
; Preferences survive app removal; no analysis directory is deleted by Uninstall.
Root: HKCU; Subkey: "Software\NIPAT\desktop"; ValueType: string; ValueName: "app_dir"; ValueData: "{app}"
Root: HKCU; Subkey: "Software\NIPAT\desktop"; ValueType: string; ValueName: "runtime_dir"; ValueData: "{code:GetNipatRuntimeDir}"
Root: HKCU; Subkey: "Software\NIPAT\desktop"; ValueType: string; ValueName: "cache_dir"; ValueData: "{code:GetNipatCacheDir}"
Root: HKCU; Subkey: "Software\NIPAT\desktop"; ValueType: string; ValueName: "data_dir"; ValueData: "{code:GetNipatDataDir}"
Root: HKCU; Subkey: "Software\NIPAT\desktop"; ValueType: string; ValueName: "runs_dir"; ValueData: "{code:GetNipatRunsDir}"

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento {#NipatDisplayName} sul desktop"

[Icons]
Name: "{autodesktop}\{#NipatDisplayName}"; Filename: "{app}\2_AVVIA.cmd"; WorkingDir: "{code:GetNipatDataDir}"; IconFilename: "{app}\assets\branding\nipat-icon.ico"; Tasks: desktopicon
Name: "{group}\{#NipatDisplayName}"; Filename: "{app}\2_AVVIA.cmd"; WorkingDir: "{code:GetNipatDataDir}"; IconFilename: "{app}\assets\branding\nipat-icon.ico"
Name: "{group}\{#NipatDisplayName} - completa preparazione"; Filename: "{app}\1_SETUP.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\assets\branding\nipat-icon.ico"
Name: "{group}\Cartella {#NipatDisplayName}"; Filename: "{app}"
Name: "{group}\Guida {#NipatDisplayName}"; Filename: "{app}\docs\GUIDA_UTILIZZO.md"
Name: "{group}\Disinstalla {#NipatDisplayName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\2_AVVIA.cmd"; Description: "Avvia {#NipatDisplayName}"; WorkingDir: "{code:GetNipatDataDir}"; Flags: postinstall nowait skipifsilent; Check: CanLaunchNipat

[Code]
var
  BootstrapResult: Integer;
  BootstrapCompleted: Boolean;
  WslRebootRequired: Boolean;
  StoragePage: TInputDirWizardPage;
  LayoutHelpersExtracted: Boolean;
  ApplicationKind: String;
  ProposedParent: String;

function NipatGetDriveType(RootPath: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function NipatRememberedPath(Name, DefaultPath: String): String;
begin
  Result := DefaultPath;
  RegQueryStringValue(HKCU, 'Software\NIPAT\desktop', Name, Result);
  if Trim(Result) = '' then Result := DefaultPath;
end;

function GetNipatDefaultAppDir(Param: String): String;
begin
  Result := NipatRememberedPath('app_dir',
    ExpandConstant('{localappdata}\Programs\{#NipatAppDirectory}'));
end;

function GetNipatRuntimeDir(Param: String): String;
begin
  Result := StoragePage.Values[0];
end;

function GetNipatCacheDir(Param: String): String;
begin
  Result := StoragePage.Values[1];
end;

function GetNipatDataDir(Param: String): String;
begin
  Result := StoragePage.Values[2];
end;

function GetNipatRunsDir(Param: String): String;
begin
  Result := StoragePage.Values[3];
end;

function CanLaunchNipat(): Boolean;
begin
  Result := BootstrapCompleted and (BootstrapResult = 0) and not WslRebootRequired;
end;

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

function NipatPathsOverlap(LeftPath, RightPath: String): Boolean;
begin
  LeftPath := AddBackslash(RemoveBackslashUnlessRoot(LeftPath));
  RightPath := AddBackslash(RemoveBackslashUnlessRoot(RightPath));
  Result := (CompareText(Copy(LeftPath, 1, Length(RightPath)), RightPath) = 0) or
    (CompareText(Copy(RightPath, 1, Length(LeftPath)), LeftPath) = 0);
end;

function NipatValidatePath(var Path: String; LabelText: String): String;
var
  I: Integer;
  Letter: String;
begin
  Result := '';
  Path := Trim(Path);
  StringChangeEx(Path, '/', '\', True);
  if Length(Path) < 4 then begin
    Result := LabelText + ': scegliere una sottocartella su un disco locale, non la radice del disco.';
    Exit;
  end;
  Letter := Uppercase(Copy(Path, 1, 1));
  if (Letter < 'A') or (Letter > 'Z') or (Copy(Path, 2, 2) <> ':\') then begin
    Result := LabelText + ': inserire un percorso completo su un disco locale fisso, per esempio D:\NIPAT\dati.';
    Exit;
  end;
  for I := 4 to Length(Path) do
    if (Ord(Path[I]) < 32) or (Pos(Path[I], ':*?"<>|') > 0) then begin
      Result := LabelText + ': il percorso contiene caratteri non validi.';
      Exit;
    end;
  Path := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  if Length(Path) < 4 then begin
    Result := LabelText + ': la radice del disco non e una cartella dedicata.';
    Exit;
  end;
  if NipatGetDriveType(Copy(Path, 1, 3)) <> 3 then begin
    Result := LabelText + ': scegliere un disco locale fisso disponibile. Unita di rete e rimovibili non sono supportate.';
    Exit;
  end;
  if FileExists(Path) then begin
    Result := LabelText + ': il percorso identifica un file, non una cartella.';
    Exit;
  end;
  if NipatPathsOverlap(Path, ExpandConstant('{win}')) or
     NipatPathsOverlap(Path, ExpandConstant('{commonpf32}')) or
     NipatPathsOverlap(Path, ExpandConstant('{commonpf64}')) or
     NipatPathsOverlap(Path, ExpandConstant('{localappdata}\Programs\NIPAT')) or
     NipatPathsOverlap(Path, ExpandConstant('{localappdata}\NIPAT')) or
     NipatPathsOverlap(Path, ExpandConstant('{localappdata}\Programs\NIPAT-0.5-Preview')) or
     NipatPathsOverlap(Path, ExpandConstant('{localappdata}\NIPAT-0.5-Preview')) or
     NipatPathsOverlap(Path, ExpandConstant('{localappdata}\NIPAT-Desktop\preferences.json')) then begin
    Result := LabelText + ': scegliere una cartella separata da Windows, Program Files e dalle altre installazioni NIPAT.';
    Exit;
  end;
  if NipatPathHasReparsePoint(Path) then
    Result := LabelText + ': il percorso attraversa un collegamento o una junction. Scegliere la cartella fisica.';
end;

function NipatValidateSelection(): String;
var
  Paths: TArrayOfString;
  Labels: TArrayOfString;
  I, J: Integer;
begin
  Result := '';
  SetArrayLength(Paths, 5);
  SetArrayLength(Labels, 5);
  Paths[0] := WizardDirValue;
  Labels[0] := 'Applicazione';
  Labels[1] := 'Ambiente WSL';
  Labels[2] := 'Cache';
  Labels[3] := 'Dati';
  Labels[4] := 'Risultati';
  for I := 1 to 4 do Paths[I] := StoragePage.Values[I - 1];
  for I := 0 to 4 do begin
    Result := NipatValidatePath(Paths[I], Labels[I]);
    if Result <> '' then Exit;
    for J := 0 to I - 1 do
      if NipatPathsOverlap(Paths[I], Paths[J]) then begin
        Result := Labels[I] + ' e ' + Labels[J] + ': scegliere cartelle distinte, senza includerne una dentro l''altra.';
        Exit;
      end;
  end;
  for I := 0 to 2 do
    if NipatTreeHasReparsePoint(Paths[I]) then begin
      Result := Labels[I] + ': la cartella contiene collegamenti o junction. Nessun file viene copiato.';
      Exit;
    end;
  if FileOrDirExists(AddBackslash(Paths[0]) + '.git') then begin
    Result := 'La cartella applicativa contiene un progetto Git. Scegliere una cartella dedicata all''installazione.';
    Exit;
  end;
  WizardForm.DirEdit.Text := Paths[0];
  for I := 1 to 4 do StoragePage.Values[I - 1] := Paths[I];
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  ModeText, PreservationText: String;
begin
  ModeText := 'Installazione';
  PreservationText := 'Dati e risultati gia presenti vengono conservati.';
  if (ApplicationKind = 'installed') or (ApplicationKind = 'residual') then begin
    ModeText := 'Aggiornamento e riparazione';
    PreservationText := PreservationText + ' Prima della copia viene salvato un backup dei file applicativi ' +
      'che saranno sostituiti. Gli altri file presenti restano nella cartella. ' +
      'Il backup non comporta un ripristino automatico.';
  end;
  Result := 'Operazione: ' + ModeText + NewLine + NewLine + PreservationText + NewLine + NewLine +
    MemoDirInfo + NewLine + NewLine +
    'Ambiente di calcolo WSL:' + NewLine + Space + GetNipatRuntimeDir('') + NewLine + NewLine +
    'Cache dei componenti:' + NewLine + Space + GetNipatCacheDir('') + NewLine + NewLine +
    'Dati predefiniti:' + NewLine + Space + GetNipatDataDir('') + NewLine + NewLine +
    'Risultati predefiniti:' + NewLine + Space + GetNipatRunsDir('') + NewLine + NewLine +
    MemoGroupInfo + NewLine + MemoTasksInfo;
end;

function NipatJsonString(Value: String): String;
var
  I: Integer;
begin
  Result := '"';
  for I := 1 to Length(Value) do begin
    if Value[I] = '\' then Result := Result + '\\'
    else if Value[I] = '"' then Result := Result + '\"'
    else Result := Result + Value[I];
  end;
  Result := Result + '"';
end;

procedure WriteNipatInstallLayoutAt(LayoutPath: String);
var
  Lines: TArrayOfString;
  LayoutDir: String;
begin
  LayoutDir := ExtractFileDir(LayoutPath);
  if not ForceDirectories(LayoutDir) then
    RaiseException('Impossibile creare la cartella di configurazione: ' + LayoutDir);
  SetArrayLength(Lines, 9);
  Lines[0] := '{';
  Lines[1] := '  "schema_version": 1,';
  Lines[2] := '  "installation_channel": "desktop",';
  Lines[3] := '  "app_dir": ' + NipatJsonString(ExpandConstant('{app}')) + ',';
  Lines[4] := '  "runtime_dir": ' + NipatJsonString(GetNipatRuntimeDir('')) + ',';
  Lines[5] := '  "cache_dir": ' + NipatJsonString(GetNipatCacheDir('')) + ',';
  Lines[6] := '  "data_dir": ' + NipatJsonString(GetNipatDataDir('')) + ',';
  Lines[7] := '  "runs_dir": ' + NipatJsonString(GetNipatRunsDir(''));
  Lines[8] := '}';
  if not SaveStringsToUTF8File(LayoutPath, Lines, False) then
    RaiseException('Impossibile salvare le cartelle selezionate: ' + LayoutPath);
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

procedure ExtractNipatLayoutHelpers;
begin
  if LayoutHelpersExtracted then Exit;
  ExtractTemporaryFile('install-profile.ps1');
  ExtractTemporaryFile('install-profile.json');
  ExtractTemporaryFile('install-layout.ps1');
  ExtractTemporaryFile('validate-install-layout.ps1');
  ExtractTemporaryFile('repair-installation.ps1');
  ExtractTemporaryFile('application-files.json');
  LayoutHelpersExtracted := True;
end;

function NipatReadValidationError(ErrorFile, Fallback: String): String;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if LoadStringsFromFile(ErrorFile, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      Result := Result + Lines[I] + #13#10;
  if Trim(Result) = '' then Result := Fallback;
end;

function NipatValidateWithSharedRules(): String;
var
  LayoutFile, ErrorFile, InfoFile, Parameters: String;
  ValidationResult: Integer;
begin
  Result := '';
  ApplicationKind := '';
  LayoutFile := ExpandConstant('{tmp}\nipat-layout-selection.json');
  ErrorFile := ExpandConstant('{tmp}\nipat-layout-error.txt');
  InfoFile := ExpandConstant('{tmp}\nipat-layout-info.ini');
  try
    ExtractNipatLayoutHelpers;
    WriteNipatInstallLayoutAt(LayoutFile);
    DeleteFile(ErrorFile);
    DeleteFile(InfoFile);
    Parameters := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' +
      QuoteNipatArgument(ExpandConstant('{tmp}\validate-install-layout.ps1')) +
      ' -LayoutFile ' + QuoteNipatArgument(LayoutFile) +
      ' -InfoFile ' + QuoteNipatArgument(InfoFile) +
      ' -ErrorFile ' + QuoteNipatArgument(ErrorFile);
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ValidationResult) then
      ValidationResult := 1;
    ApplicationKind := GetIniString('NIPAT', 'kind', '', InfoFile);
    if ValidationResult <> 0 then
      Result := NipatReadValidationError(ErrorFile,
        'Impossibile verificare le cartelle selezionate. Nessun file viene copiato. ' +
        'Verificare che Windows consenta l''esecuzione di PowerShell e riprovare.')
    else if (ApplicationKind <> 'empty') and (ApplicationKind <> 'installed') and
      (ApplicationKind <> 'residual') then
      Result := 'La verifica non ha riconosciuto la destinazione applicativa. Nessun file viene copiato.';
  except
    Result := 'Verifica delle cartelle non completata: ' + GetExceptionMessage;
  end;
end;

function NipatDirectoryIsEmpty(Path: String): Boolean;
var
  Entry: TFindRec;
begin
  Result := not FileExists(Path);
  if not Result or not DirExists(Path) then Exit;
  if not FindFirst(AddBackslash(Path) + '*', Entry) then begin
    Result := False;
    Exit;
  end;
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
        Result := False;
        Exit;
      end;
    until not FindNext(Entry);
  finally
    FindClose(Entry);
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  MessageText, ParentPath, ChildPath: String;
begin
  Result := True;
  if CurPageID <> StoragePage.ID then Exit;
  ApplicationKind := '';
  MessageText := NipatValidateSelection;
  if MessageText = '' then MessageText := NipatValidateWithSharedRules;
  if (MessageText <> '') and (ApplicationKind = 'unknown') and not WizardSilent then begin
    ParentPath := WizardDirValue;
    ChildPath := AddBackslash(ParentPath) + '{#NipatAppDirectory}';
    if (CompareText(ProposedParent, ParentPath) <> 0) and
      (CompareText(ExtractFileName(ParentPath), '{#NipatAppDirectory}') <> 0) and
      NipatDirectoryIsEmpty(ChildPath) then begin
      ProposedParent := ParentPath;
      if MsgBox('La cartella selezionata contiene file che non identificano un''installazione NIPAT. ' +
        'Vuoi usare questa sottocartella dedicata e vuota?' + #13#10#13#10 + ChildPath + #13#10#13#10 +
        'Nessun file esistente verra spostato o eliminato. Scegli No per tornare indietro e indicare un''altra destinazione.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then begin
        WizardForm.DirEdit.Text := ChildPath;
        MessageText := NipatValidateSelection;
        if MessageText = '' then MessageText := NipatValidateWithSharedRules;
      end;
    end;
  end;
  if MessageText <> '' then begin
    MsgBox(MessageText + #13#10#13#10 + 'Usa Indietro per modificare la cartella applicativa.', mbError, MB_OK);
    Result := False;
  end;
end;

function NipatPrepareApplication(): String;
var
  LayoutFile, ErrorFile, ReportFile, Parameters, Mode, BackupDir: String;
  RepairResult: Integer;
begin
  Result := '';
  LayoutFile := ExpandConstant('{tmp}\nipat-layout-selection.json');
  ErrorFile := ExpandConstant('{tmp}\nipat-repair-error.txt');
  ReportFile := ExpandConstant('{tmp}\nipat-repair-report.ini');
  try
    ExtractNipatLayoutHelpers;
    WriteNipatInstallLayoutAt(LayoutFile);
    DeleteFile(ErrorFile);
    DeleteFile(ReportFile);
    Parameters := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' +
      QuoteNipatArgument(ExpandConstant('{tmp}\repair-installation.ps1')) +
      ' -LayoutFile ' + QuoteNipatArgument(LayoutFile) +
      ' -PayloadFile ' + QuoteNipatArgument(ExpandConstant('{tmp}\application-files.json')) +
      ' -ReportFile ' + QuoteNipatArgument(ReportFile) +
      ' -ErrorFile ' + QuoteNipatArgument(ErrorFile);
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, RepairResult) then
      RepairResult := 1;
    if RepairResult <> 0 then begin
      Result := NipatReadValidationError(ErrorFile,
        'Preparazione o backup dell''applicazione non completati. Nessun file applicativo viene copiato.');
      Exit;
    end;
    Mode := GetIniString('NIPAT', 'mode', '', ReportFile);
    BackupDir := GetIniString('NIPAT', 'backup_dir', '', ReportFile);
    if (Mode <> 'install') and (Mode <> 'repair') then
      Result := 'Rapporto di preparazione non valido. Nessun file applicativo viene copiato.'
    else if (Mode = 'repair') and ((BackupDir = '') or not DirExists(BackupDir)) then
      Result := 'Backup della riparazione non disponibile. Nessun file applicativo viene copiato.'
    else if Mode = 'repair' then
      Log('Backup prima della riparazione: ' + BackupDir);
  except
    Result := 'Preparazione dell''applicazione non completata: ' + GetExceptionMessage;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := NipatValidateSelection;
  if (Result = '') and (CompareText(WizardGroupValue, '{#NipatDisplayName}') <> 0) then
    Result := 'Il gruppo Start di NIPAT Desktop deve restare separato dalle altre installazioni. Riavviare senza /GROUP.';
  if Result = '' then Result := NipatValidateWithSharedRules;
  if Result = '' then Result := NipatPrepareApplication;
end;

procedure ReadNipatPreviousDefaults(Project, DefaultsFile: String);
var
  Parameters, ErrorFile: String;
  ValidationResult: Integer;
begin
  ExtractNipatLayoutHelpers;
  ErrorFile := ExpandConstant('{tmp}\nipat-defaults-error.txt');
  DeleteFile(ErrorFile);
  Parameters := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' +
    QuoteNipatArgument(ExpandConstant('{tmp}\validate-install-layout.ps1')) +
    ' -Project ' + QuoteNipatArgument(Project) +
    ' -DefaultsFile ' + QuoteNipatArgument(DefaultsFile) +
    ' -ErrorFile ' + QuoteNipatArgument(ErrorFile);
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parameters, ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ValidationResult) then
    ValidationResult := 1;
  if ValidationResult <> 0 then
    RaiseException(NipatReadValidationError(ErrorFile,
      'Impossibile leggere le cartelle della precedente installazione. ' +
      'Conservare la configurazione esistente e verificare che Windows consenta PowerShell.'));
end;

procedure InitializeWizard();
var
  Base, Project, DefaultsFile, Stored: String;
  Names, Defaults: TArrayOfString;
  I: Integer;
  NeedPrevious: Boolean;
begin
  Base := ExpandConstant('{localappdata}\{#NipatDataDirectory}');
  SetArrayLength(Names, 4);
  SetArrayLength(Defaults, 4);
  Names[0] := 'runtime_dir'; Defaults[0] := AddBackslash(Base) + 'wsl';
  Names[1] := 'cache_dir'; Defaults[1] := AddBackslash(Base) + 'cache';
  Names[2] := 'data_dir'; Defaults[2] := AddBackslash(Base) + 'data';
  Names[3] := 'runs_dir'; Defaults[3] := AddBackslash(Base) + 'runs';
  NeedPrevious := False;
  for I := 0 to 3 do
    if not RegQueryStringValue(HKCU, 'Software\NIPAT\desktop', Names[I], Stored) then
      NeedPrevious := True
    else if Trim(Stored) = '' then NeedPrevious := True;
  Project := WizardDirValue;
  if NeedPrevious and
    (FileExists(AddBackslash(Project) + '.runtime\install-layout.json') or
     FileExists(AddBackslash(Project) + '.runtime\backend.json')) then begin
    DefaultsFile := ExpandConstant('{tmp}\nipat-previous-paths.ini');
    ReadNipatPreviousDefaults(Project, DefaultsFile);
    for I := 0 to 3 do Defaults[I] := GetIniString('NIPAT', Names[I], Defaults[I], DefaultsFile);
  end;
  StoragePage := CreateInputDirPage(wpSelectDir,
    'Cartelle di NIPAT', 'Scegli dove conservare ambiente di calcolo e analisi.',
    'Puoi mantenere le destinazioni proposte oppure scegliere cartelle distinte, anche su altri dischi locali. ' +
    'I file gia presenti non vengono spostati; un nuovo ambiente WSL viene preparato nella destinazione scelta.',
    False, SetupMessage(msgNewFolderName));
  StoragePage.Add('Ambiente di calcolo WSL:');
  StoragePage.Add('Cache dei componenti di installazione:');
  StoragePage.Add('Cartella dati predefinita:');
  StoragePage.Add('Cartella risultati predefinita:');
  for I := 0 to 3 do StoragePage.Values[I] := NipatRememberedPath(Names[I], Defaults[I]);
end;

function InitializeUninstall(): Boolean;
begin
  Result := not IsAdmin;
  if not Result then
    MsgBox('Eseguire la disinstallazione dal proprio account senza elevazione. ' +
      'L''ambiente WSL appartiene all''utente che ha installato NIPAT.', mbError, MB_OK);
end;

procedure RemoveNipatRuntimeBeforeUninstall;
var
  CleanupResult: Integer;
  Parameters: String;
begin
  Parameters := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' +
    QuoteNipatArgument(ExpandConstant('{app}\installer\windows\uninstall-runtime.ps1')) +
    ' -Project ' + QuoteNipatArgument(ExpandConstant('{app}'));
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parameters, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, CleanupResult) then
    CleanupResult := 1;
  if CleanupResult <> 0 then
    RaiseException('La pulizia dell''ambiente non e stata completata. L''applicazione non viene rimossa, ' +
      'Consulta i log in ' + ExpandConstant('{localappdata}\{#NipatDataDirectory}\installations\logs') + '. ' +
      'Per rimuovere soltanto l''applicazione, ' +
      'riapri la disinstallazione e scegli No alla pulizia dell''ambiente.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AssetDir, Parameters: String;
  Started: Boolean;
begin
  if CurStep = ssPostInstall then begin
    WriteNipatInstallLayoutAt(ExpandConstant('{app}\.runtime\install-layout.json'));
    AssetDir := ExpandConstant('{param:ASSETDIR|}');
    Parameters := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' +
      QuoteNipatArgument(ExpandConstant('{app}\installer\windows\bootstrap.ps1'));
    if AssetDir <> '' then
      Parameters := Parameters + ' -AssetDirectory ' + QuoteNipatArgument(AssetDir);
    Started := ExecAsOriginalUser(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, BootstrapResult);
    if not Started then BootstrapResult := 1;
    BootstrapCompleted := True;
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
var
  Choice: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    { This point is after Inno's confirmation and before any installed file is removed. }
    { Silent removal conserves runtime and data; interactive cleanup is opt-in. }
    if not UninstallSilent then begin
      Choice := MsgBox('Rimuovere anche gli ambienti WSL e la cache appartenenti a NIPAT Desktop?'#13#10#13#10 +
        'Si: elimina definitivamente le distribuzioni NIPAT Desktop riconosciute, tutti i file al loro interno e gli archivi della cache.'#13#10 +
        'No: conserva questi componenti per una reinstallazione.'#13#10#13#10 +
        'Dati e risultati delle analisi su Windows, Docker Desktop e altre distribuzioni Linux vengono conservati.',
        mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON2);
      if Choice = IDCANCEL then Abort;
      if Choice = IDYES then RemoveNipatRuntimeBeforeUninstall;
    end;
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce', '{#NipatResumeKey}');
  end;
end;
