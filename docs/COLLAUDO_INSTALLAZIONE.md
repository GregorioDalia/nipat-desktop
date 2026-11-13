# Collaudo automatico dell'installazione Windows

Dalla 0.8.60 il pacchetto include il collaudo dei cinque moduli e dei workflow.
Non servono Python, R o Docker Desktop installati separatamente. Completare
prima il setup NIPAT; il collaudo usa il suo Python e il runtime WSL verificato.

Aprire **Windows PowerShell come utente normale** e incollare:

```powershell
$app = (Get-ItemProperty -LiteralPath 'HKCU:\Software\NIPAT\desktop' -Name app_dir).app_dir
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'scripts\windows\test-installed.ps1')
```

Il comando non cambia le policy persistenti di Windows. La finestra indica
la cartella creata sotto `%LOCALAPPDATA%\NIPAT-Desktop\collaudi`. Attendere
l'esito; il report HTML si apre al termine. Per condividere i risultati,
usare `report.zip` della nuova sessione.

## Cosa controlla

- Identità dell'installazione, runtime, impostazioni e risorse.
- Risultati numerici di DNP, SNP, Contamination, CPI e CPIN con attese indipendenti.
- Workflow da tre BAM, da pileup SNP e da tabelle; composizioni dei cinque moduli.
- Identità dei campioni, ruoli familiari, parametri e output prodotti realmente.
- Tabelle scientifiche identiche fra seriale, automatico e limite di due processi.
- Rifiuto di input non validi per il motivo atteso, senza scambiare un errore
  d'ambiente per un corretto rifiuto scientifico.
- Integrità degli input, dell'installazione, delle preferenze e del collaudo.

La matrice corrente comprende 54 esecuzioni (48 positive e 6 rifiuti attesi),
9 confronti di riproducibilità e 7 controlli preliminari/finali. Su un ambiente
completo l'esito atteso è **70 PASS, 0 FAIL, 0 BLOCKED, 0 INTERRUPTED**.
Le prove mancanti o interrotte non vengono conteggiate come superate.

Le fixture sono sintetiche e la loro provenienza rimane registrata separatamente
dalla versione installata. Il collaudo non seleziona file biologici dell'utente,
non aggiorna l'applicazione e non modifica le preferenze. Crea soltanto i propri
input, run e report. Uno ZIP può contenere percorsi locali e informazioni sul
PC: controllarlo prima di condividerlo pubblicamente.

Il tempo dipende dalle risorse del PC. La precedente esecuzione completa sulla
0.8.50 riparata ha richiesto circa 11 minuti; non è una misura di velocità sui
BAM reali. Un esito positivo verifica questa matrice sintetica, non ogni input
possibile o una validazione clinica.
