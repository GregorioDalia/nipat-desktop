<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/branding/nipat-logo-dark.svg">
  <img src="assets/branding/nipat-logo.svg" alt="NIPAT" width="335">
</picture>

# NIPAT Desktop

NIPAT Desktop esegue sul computer analisi SNP e DNP, stima della contaminazione
e calcolo dell'indice combinato di paternità prenatale e postnatale.
Si usa da un **menu testuale guidato** o da **riga di comando**. Le analisi
usano il runtime scientifico locale con R e samtools. Dopo la preparazione
dell'ambiente, i calcoli si possono eseguire offline.

## Download

Scarica il pacchetto per il tuo sistema. La
[release stabile 0.8.60](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.60)
riporta anche checksum e verifiche dei pacchetti.

| Sistema | Pacchetto | Guida |
| --- | --- | --- |
| Windows 10 22H2 x64 (build 19045) o Windows 11 x64 | [Setup Windows](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.60/NIPAT-Setup.exe) | [Windows](docs/INSTALLATORE_WINDOWS.md) |
| macOS 14 o successivo, Apple Silicon | [Pacchetto ARM64](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.60/NIPAT-0.8.60-macos-arm64.pkg) | [macOS](docs/INSTALLATORE_MACOS.md) |
| macOS 14 o successivo, Intel | [Pacchetto Intel](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.60/NIPAT-0.8.60-macos-x86_64.pkg) | [macOS](docs/INSTALLATORE_MACOS.md) |
| Ubuntu 24.04 LTS x86_64 | [Pacchetto DEB](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.60/nipat-desktop_0.8.60_amd64.deb) | [Ubuntu](docs/INSTALLATORE_LINUX.md) |

Windows usa WSL2, macOS usa Lima e Ubuntu usa il Docker Engine locale.
La [guida alla distribuzione](docs/DISTRIBUZIONE.md) spiega i prerequisiti,
la preparazione al primo avvio, gli aggiornamenti e la rimozione.
Per gli avvisi del sistema sulla firma del pacchetto, consulta la guida della
tua piattaforma.

## Analisi

| Modulo | Dati da preparare | Risultati principali |
| --- | --- | --- |
| **DNPcall** | Uno o più BAM, FASTA indicizzato e pannello DNP | Conteggi e genotipi per campione, riepiloghi e grafici |
| **SNPcall 2.0** | BAM e FASTA indicizzato oppure pileup con qualità e QNAME. Pannello SNP in entrambi i casi | Conteggi, likelihood, genotipi, statistiche sugli indel e grafici |
| **Contamination** | Tabelle di conteggi SNP o DNP e pannello di coordinate coerente | Stime per sito e riepilogo per campione |
| **CPI prenatale** | Conteggi SNP o DNP, coppie cfDNA materno/padre e frequenze di popolazione | Frazione fetale, indice combinato di paternità e grafici |
| **CPIN postnatale** | Conteggi SNP o DNP, trii madre/padre/figlio e frequenze di popolazione | Indici di paternità per sito, indice combinato e grafici |

Ogni modulo si può eseguire da solo. I **workflow automatici** collegano i
conteggi di DNPcall, SNPcall o entrambi a una selezione di Contamination, CPI e
CPIN. Il workflow può partire anche da pileup SNP o tabelle compatibili già
generate. Ogni ramo usa i propri pannelli e frequenze. Le coppie e i trii si
definiscono associando esplicitamente i campioni ai ruoli. Contamination,
CPI e CPIN ricevono le tabelle dei caller come input indipendenti.

## Prima analisi

1. Apri **NIPAT Desktop** e scegli il modulo o **Workflow automatici**.
2. Seleziona gli input e i parametri. Con un BAM, scegli il FASTA delle
   sequenze, per esempio `genome.fa`, e tieni l'indice `genome.fa.fai` accanto
   al riferimento. Per i FASTA BGZF serve anche `.gzi`.
3. Controlla il riepilogo e la cartella dei risultati, quindi scegli
   **Avvia analisi**.
4. Apri il resoconto `run-report.html` e le tabelle dalla cartella del run.

La [guida per l'utilizzo](docs/GUIDA_UTILIZZO.md) contiene i formati dei file,
i comandi per ogni modulo e gli esempi con coppie e trii. Su Windows usa
percorsi su dischi locali fissi.

Per eseguire DNPcall da PowerShell, dalla cartella dell'applicazione:

```powershell
.\nipat.cmd dnp-call --bam "C:\Dati\campione.bam" `
  --reference "C:\Dati\genome.fa" --panel "C:\Dati\DNP_list.txt"
```

Su Ubuntu usa il comando `nipat`. Su macOS usa
`"/Applications/NIPAT Desktop.app/Contents/Resources/NIPAT.command"`.
L'opzione `--help` elenca i comandi. `settings` mostra i valori scientifici
effettivi e `parameters` consulta il catalogo di parametri, regole e
preparazione degli input. Dal menu trovi queste informazioni in
**Configura** e **Guida e informazioni**.

## Risultati e prestazioni

Ogni analisi crea una cartella con i risultati in `output`, il record
`run.json` e il log `execution.log`. I workflow conservano anche lo stato
e gli output di ogni passaggio. Il record riporta input, parametri,
runtime e avvisi. Le tabelle di consultazione associano gli identificativi
interni ai nomi originali dei campioni. Gli input al motore sono in sola
lettura. Un esito `succeeded` attesta il completamento tecnico e i controlli
previsti per il run. La valutazione scientifica richiede dati di riferimento
e criteri appropriati al caso.

Puoi scegliere esecuzione seriale, parallelismo automatico o un limite di
processi. Nel riepilogo seleziona **Avvia analisi con diagnostica prestazioni**
per registrare tempi, attività dei processi e misure di risorse per quel run.
Consulta la [guida alle esecuzioni](docs/ESECUZIONI.md) per interpretare
stati e risultati, e la [guida alle prestazioni](docs/PERFORMANCE.md) per
impostare un benchmark riproducibile.

## Documentazione e licenza

L'[indice della documentazione](https://github.com/GregorioDalia/nipat-desktop/blob/main/docs/README.md) raccoglie le guide per
piattaforma, i contratti scientifici e le istruzioni di sviluppo e rilascio.
Su Windows è disponibile il
[collaudo sintetico dell'installazione](docs/COLLAUDO_INSTALLAZIONE.md).

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](LICENSE). Le licenze e le attribuzioni dei componenti
inclusi sono in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
