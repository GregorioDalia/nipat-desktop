# Guida alla prova della CLI

Questa versione serve a verificare il funzionamento dei quattro workflow e
l'adeguatezza dei risultati con input scelti dall'esperta di dominio. La GUI
non è ancora presente: si può usare un menu testuale oppure la riga di comando.

## Preparazione su Windows a 64 bit

1. Installa e avvia [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/),
   usando container Linux. Completa gli eventuali passaggi WSL richiesti da Docker.
2. Dal link alla versione GitHub indicata per la validazione, scarica
   l'archivio del progetto (nelle release: **Source code (zip)**).
   Estrailo interamente in una cartella locale scrivibile,
   preferibilmente con un percorso breve, per esempio `D:\Nipat_validazione`.
   Non avviare i file direttamente dalla finestra dello ZIP.
3. Nella cartella estratta che contiene `README.md` e `1_SETUP.cmd`, avvia
   `1_SETUP.cmd`. Il nome della cartella può includere il tag della versione.
   Il setup prepara Python locale,
   le cartelle di lavoro e il runtime, poi esegue i controlli iniziali.
4. Quando il setup termina con esito positivo, avvia `2_AVVIA.cmd`.

Non servono Git, PyCharm, un'installazione separata di Python, R o samtools.
Il setup scarica Python e costruisce il runtime Docker quando non è già
disponibile. Servono Internet e tempo per la prima preparazione; i successivi
avvii riusano l'ambiente locale.
Il setup non installa automaticamente Docker e non cambia il Python di sistema.

Le cartelle `data` e `runs` vengono create accanto alla cartella del progetto:

| Cartella | Contenuto |
| --- | --- |
| `data/samples` | BAM, relativi indici e altri input dei campioni. |
| `data/reference` | FASTA e relativo indice. |
| `data/panels` | Pannelli DNP/SNP e frequenze di popolazione. |
| `data/test-cases` | Tabelle di prova, incluse quelle per CPI. |
| `runs` | Nuove esecuzioni e relativi risultati. |

Sono accettati percorsi all'interno del progetto, di `data` o di `runs`.
Per provare file conservati altrove, copiarli in queste cartelle. Il progetto
non contiene BAM, riferimenti genomici o campioni reali da distribuire.

## Prima prova

Il setup esegue `nipat self-test`: verifica l'esempio SNPcall e i casi sintetici
CPI e Contamination inclusi nel pacchetto. Questi controlli non richiedono i
campioni dell'utilizzatrice e creano nuovi run. Attendere il messaggio finale
di autotest superati: per CPI e Contamination il confronto numerico segue
il completamento del workflow, quindi un `run.json` con esito positivo
non basta, da solo, a dimostrare il superamento dell'autotest.
Questi controlli non sostituiscono la prova
DNPcall da BAM né la valutazione scientifica con i propri dati.

Per ripeterli, aprire PowerShell nella cartella che contiene `nipat.cmd`:

```powershell
.\nipat.cmd doctor --runtime
.\nipat.cmd self-test
```

## Input dei quattro workflow

**DNPcall.** Richiede un BAM con il file `.bam.bai`, un FASTA con il file
`.fa.fai` (o il corrispondente nome del FASTA seguito da `.fai`) e un pannello
tabulato senza intestazione: `chr`, `pos1`, `pos2`, `REF`, `ALT`.
Le due posizioni devono essere adiacenti e gli alleli devono essere dinucleotidi.
Per un singolo campione il grafico UpSet è intenzionalmente omesso.
Per un limite dello script DNPcall, usare nomi BAM/FASTA e sottocartelle
senza spazi o simboli shell all'interno di `data` o `runs`, per esempio
`samples/sample_01.bam` e `reference/genome.fa`. Il controllo iniziale segnala
i percorsi incompatibili. Questa restrizione non riguarda gli spazi nel
percorso Windows che precede le cartelle montate nel container.

**SNPcall.** Richiede BAM e FASTA indicizzati e una lista tabulata con
intestazione `pos`, `ref`, `alt`; `pos` ha forma `chr1:1770788`.
Il programma prepara le regioni e il pileup automaticamente. Il totale include
le letture “altre”; il rapporto REF usa soltanto REF e ALT nel denominatore.

**Contamination.** Richiede una o più tabelle tabulate con `chr`, `pos1`,
`pos2`, `N_REF`, `N_ALT`, `N_Other` e un pannello DNP. Gli output individuali
DNPcall sono compatibili. Se presente, `ratio_REF_ALT` viene usato dallo script;
se assente, viene calcolato dai conteggi. Le stime sono frazioni: `0.025`
significa 2.5%. Zero e `NA` hanno significati diversi: `NA` può indicare
l'assenza di siti informativi.

**CPI.** Richiede una cartella con tabelle compatibili DNPcall della componente
cfDNA materna e del presunto padre. Con i prefissi predefiniti, la coppia `A1:A1`
individua `MotherA1.txt` e `FatherA1.txt`. Più coppie si separano con virgole.
La tabella delle frequenze deve includere `chr`, `pos1`, `pos2`, `Ref_f.pop`,
`Alt_f.pop`. La scelta dei campioni, del pannello, del riferimento genomico
e delle frequenze deve essere coerente con il caso da valutare. Non dedurre
il ruolo biologico di un campione dal solo nome del file.

## Esecuzione e lettura dell'esito

`2_AVVIA.cmd` chiede il workflow, gli input e i parametri necessari. Per i
percorsi si può incollare il percorso completo, anche racchiuso tra virgolette;
per DNPcall valgono le restrizioni indicate sopra. Scegliere un nome
nuovo per ciascun run oppure lasciare il nome automatico.

Per i comandi diretti:

```powershell
.\nipat.cmd --help
.\nipat.cmd contamination --help
.\nipat.cmd --dry-run contamination --input "D:\Nipat_validazione\data\samples\sample.txt" --panel "D:\Nipat_validazione\data\panels\DNP_list.txt"
```

`--dry-run` controlla e prepara l'esecuzione mostrando i comandi; non esegue
l'analisi scientifica. Usare un nome nuovo anche per la successiva prova reale.

Ogni run conserva `run.json`, `execution.log`, `work` e `output`. L'esito
positivo indica il completamento dei comandi del workflow; la valutazione dei
risultati è affidata all'esperta. Una cartella con output parziali, o un run che
non ha registrato un esito finale, non dimostra il completamento dell'analisi.
Le esecuzioni precedenti a questa versione possono essere prive dei metadati.

## Problemi e feedback

- Se Docker non risponde, avviare Docker Desktop e attendere che il motore Linux
  sia pronto, poi riprovare.
- Se il percorso non è ammesso, spostare una copia dell'input in `data` o usare
  direttamente un risultato sotto `runs`.
- Se manca un indice, fornire l'indice corrispondente al BAM/FASTA selezionato.
- Se il nome del run esiste già, sceglierne uno nuovo.
- Se una prova fallisce, conservare il run e compilare
  [la scheda di validazione](VALIDAZIONE.md) indicando atteso e osservato.

I log e i metadati possono contenere nomi e percorsi dei campioni. Prima di
allegarli a una segnalazione pubblica, verificare che siano condivisibili.
Non caricare su GitHub BAM, riferimenti o risultati contenenti dati dei campioni.
