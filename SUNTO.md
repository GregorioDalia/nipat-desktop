# NIPAT in sintesi

**NIPAT Desktop 0.8.14** esegue DNPcall, SNPcall, Contamination e CPI sul computer
dell'utente attraverso una CLI guidata. Le analisi possono essere avviate
singolarmente oppure collegate in un workflow automatico con una sola conferma.

L'esecuzione può essere seriale oppure automatica, con un massimo di processi
configurabile. DNP prepara il pileup per cromosoma e distribuisce il calcolo
R su una coda comune di blocchi di tutti i campioni, con un budget unico anche
per un numero di BAM maggiore dei processi disponibili. I blocchi iniziali
sono da 32 MiB di input grezzo / 64 loci. La diagnostica delle prestazioni è
facoltativa. Le [note della versione](docs/RELEASE_0.8.14.md) distinguono
funzionamento, prove automatiche e misure osservate sul candidato precedente.

| Analisi | Funzione |
| --- | --- |
| DNPcall | Conteggi e genotipi di dinucleotidi da uno o più BAM. |
| SNPcall | Conteggi SNP da BAM o pileup con nomi delle letture. |
| Contamination | Stima della contaminazione da tabelle di conteggi compatibili. |
| CPI | Stima della frazione fetale e calcolo dell'indice di paternità. |

I workflow automatici collegano **DNPcall → Contamination**, **DNPcall → CPI**
oppure **DNPcall → Contamination e CPI**. SNPcall può essere aggiunto sugli stessi
BAM, con il proprio pannello, o eseguito su più campioni. Le coppie per CPI
richiedono l'assegnazione esplicita dei ruoli; il programma non deduce relazioni
biologiche dai nomi dei file.

Il client Python raccoglie gli input e controlla l'esecuzione. Una sola immagine
scientifica contiene R, samtools, dipendenze, script scientifici e orchestrazione.
Windows usa WSL2, macOS una VM Lima, Ubuntu Docker Engine locale. Su Apple Silicon
il container Linux AMD64 viene eseguito tramite Rosetta. Gli input sono letti
senza modificarli; ogni run conserva risultati, intermedi, parametri e log.

## Installazione

Scaricare il pacchetto del proprio sistema dalla pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
Gli archivi Source code sono destinati allo sviluppo.

| Sistema | Pacchetto |
| --- | --- |
| Windows 10 22H2 x64 o Windows 11 x64 | `NIPAT-Setup.exe` |
| macOS 14 o successivo, Apple Silicon | `.pkg` arm64 |
| macOS 14 o successivo, Intel | `.pkg` x86_64 |
| Ubuntu 24.04 LTS x86_64 | `.deb` amd64 |

Windows e Mac includono Python e i componenti NIPAT; non richiedono Docker Desktop.
L'attivazione di WSL o la preparazione iniziale Lima possono richiedere Internet,
autorizzazioni e, su Windows, un riavvio. Ubuntu installa le dipendenze attraverso
APT. Dopo la preparazione, le analisi si svolgono localmente senza rete.
Le [guide di installazione](docs/DISTRIBUZIONE.md) descrivono anche gli eventuali
avvisi di sicurezza e i requisiti del dispositivo.

## Utilizzo

1. Aprire NIPAT e scegliere l'analisi oppure **W — Workflow automatici**.
2. Indicare file e parametri, poi verificare il riepilogo.
3. Confermare **Avvia analisi**.
4. Consultare risultati e resoconto dell'esecuzione dalla schermata finale.

La diagnostica delle prestazioni è facoltativa e disattivata normalmente.
**Avvia analisi con diagnostica prestazioni** raccoglie le misure per quella
sola esecuzione; la [guida alle misure](docs/PERFORMANCE.md) ne descrive l'uso.

I risultati per la consultazione riportano i nomi originali dei campioni,
anche nelle etichette di tabelle e grafici. Gli identificativi interni collegano
in modo univoco le fasi; una mappa leggibile associa ogni campione ai suoi input
e risultati. File omonimi mantengono identità distinte.

**5 — Configura** gestisce cartelle, valori predefiniti e risorse.
La schermata risorse distingue memoria del computer, memoria dell'ambiente
virtuale e limite del container. Le modifiche all'ambiente richiedono un'anteprima
e una conferma; quelle che richiedono un riavvio restano indicate come non ancora
attive. Configurazione salvata, risorse effettive e suggerimenti sono distinti:
**Invio conserva i valori correnti**. Su Windows i limiti globali WSL interessano
anche le altre distribuzioni.

**6 — Ultima esecuzione** riapre risultati e log della sessione.
`:indietro` corregge un campo, `:annulla` torna al menu e **Ctrl+C** interrompe
l'operazione corrente attraverso la procedura di arresto.
Il catalogo scientifico in **Guida e informazioni** descrive parametri,
regole fisse e preparazione degli input in italiano e inglese.

Un esito tecnico positivo indica che l'analisi è terminata e gli output hanno
superato i controlli previsti. La valutazione scientifica sui campioni resta
affidata alle persone esperte di dominio.

- [Guida per l'utilizzo](docs/GUIDA_UTILIZZO.md)
- [Risultati e tracciabilità](docs/ESECUZIONI.md)
- [Risorse e memoria](docs/RISORSE.md)
- [Note della versione](docs/RELEASE_0.8.14.md)
