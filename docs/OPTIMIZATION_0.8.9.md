# Revisione scientifica 0.8.9

La 0.8.9 revisiona i quattro programmi R per ridurre allocazioni e calcoli
ripetuti e chiarisce la configurazione delle risorse. Le
[note di rilascio](RELEASE_0.8.9.md) descrivono distribuzione e perimetro delle
verifiche. Questo documento definisce il riferimento e il contratto dei
confronti scientifici.

## Riferimento

Il riferimento è la release `v0.8.5`, commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`, comprese le modifiche di
compatibilità già distribuite. Le copie immutabili dei sei file R sono in
[`tests/reference_r/0.8.5`](../tests/reference_r/0.8.5/README.md), con manifest
SHA-256. Il codice candidato rimane nelle normali directory del motore.
Le copie di riferimento sono usate soltanto dai test e non sono installate.

## Interventi

| Componente | Revisione |
| --- | --- |
| DNPcall | Preparazione diretta delle osservazioni, conversione delle qualità tramite tabella, riuso delle estrazioni da stringhe ripetute, raggruppamento unico, indici per locus ed eliminazione dei conteggi duplicati. |
| SNPcall | Lettura delle colonne utilizzate, preparazione diretta delle osservazioni e aggregazione delle caratteristiche necessarie per lettura, conservando il raggruppamento globale per QNAME. |
| CPI | Calcolo unico per coppia e pannello, selezione dei soli valori PI, riuso dei risultati fra soglie equivalenti, colonne preallocate e riuso dei campioni condivisi fra coppie consecutive. |
| Contamination | Raccolta delle righe di riepilogo e assemblaggio finale unico. |
| Configurazione risorse | Distinzione fra configurazione salvata, risorse effettive, suggerimenti e nuovi limiti; Invio conserva le impostazioni correnti. |

Le formule, le soglie, l'accesso al BAM tramite samtools e i formati dei
risultati scientifici rimangono oggetto del contratto di equivalenza.
La revisione non introduce nuovi linguaggi o dipendenze R. Modifiche alla
politica di accesso indicizzato, elaborazione per blocchi, dimensioni dei
grafici e stime del tempo residuo richiedono verifiche distinte e non sono
implicite in queste ottimizzazioni.

Nei pileup regolari, DNPcall e SNPcall separano direttamente basi, nomi e
qualità senza costruire stringhe con separatori artificiali. I casi con
valori mancanti, spazi o lunghezze non corrispondenti conservano il percorso
di preparazione compatibile. SNPcall conserva le associazioni fra letture
presenti in finestre diverse. In DNPcall le finestre sovrapposte continuano
ad assegnare le osservazioni a tutti i loci previsti.

CPI calcola una volta le statistiche delle soglie che selezionano gli stessi
loci, poi ricostruisce tutte le righe originali. Media, mediana e grafici
mantengono quindi il peso di ogni soglia. Il prodotto degli indici conserva
l'ordine originale; non viene sostituito con prodotti cumulativi o somme di
logaritmi. Il riuso dei campioni è limitato alla coppia corrente e alla
successiva, senza accumulare in memoria l'intero insieme di input.

## Criteri di equivalenza

| Output | Criterio |
| --- | --- |
| Tabelle scientifiche | Stessi file, intestazioni, ordine, valori e rappresentazione dei dati mancanti. Nessuna tolleranza numerica generale. |
| Risultati intermedi esposti dai test | Uguaglianza delle quantità non arrotondate e delle serie per soglia, per i casi coperti. |
| PDF | Stessi documenti e stessa resa delle pagine; metadati variabili come la data di creazione non richiedono byte identici. |
| Log | Conservati per diagnosi; tempi, percorsi temporanei e messaggi di raggruppamento non sono risultati scientifici. |

I test eseguono il riferimento e il candidato nello stesso ambiente,
registrando l'identità del runtime e dei sorgenti. Un esito positivo riguarda
i casi eseguiti: non dimostra equivalenza su ogni possibile input. Le fixture
coprono sia casi ordinari sia limiti delle formule e dei raggruppamenti.
I benchmark su dati esterni rimangono separati dalle fixture pubbliche.

## Esecuzione dei confronti

Dalla radice del checkout, con Docker Engine e un'immagine costruita dal
codice candidato:

```sh
docker build -f docker/scientific-runtime/Dockerfile -t nipat-scientific-runtime:r089 .
python scripts/verify_r_equivalence.py --image nipat-scientific-runtime:r089 --output-dir build/r-equivalence-089
```

Il confronto PDF richiede `pdftoppm` di Poppler sul sistema che avvia la
verifica. Usare una nuova cartella di output per ogni prova. Il rapporto
`r-equivalence.json` e i log permettono di distinguere errori di esecuzione,
alterazioni dei riferimenti e differenze nei risultati. La CI e la build
degli installatori eseguono lo stesso controllo; un confronto fallito non
viene trasformato in un successo o in un test saltato.

## Misura delle prestazioni

Il superamento dei confronti numerici precede la valutazione di velocità e
memoria. Confrontare riferimento e candidato sugli stessi input, parametri,
risorse e modalità diagnostica, registrando commit e immagine. Conservare i
risultati insieme ai tempi e ai picchi di memoria. I tempi delle fixture
non rappresentano le prestazioni su BAM grandi e non impongono soglie sui
runner condivisi. Una riduzione del lavoro ripetuto non è, da sola, una
misura del guadagno complessivo.

## Distribuzione

La pubblicazione lega sorgenti R revisionati, rapporto di equivalenza,
immagine scientifica, build e installer attraverso commit e checksum.
Il record di accettazione della 0.8.9 riguarda esclusivamente i suoi
artefatti; i record delle release precedenti non ne autorizzano la pubblicazione.
Le build per revisione e i confronti scientifici non modificano da soli
il canale stabile. La procedura è descritta in [CI/CD](CI_CD.md).

Le ottimizzazioni successive confluiscono in un unico prototipo 0.8.10,
con commit verificabili e confronti estesi. La 0.8.9 rimane la release
ufficiale finché non viene approvata una successiva pubblicazione stabile.
