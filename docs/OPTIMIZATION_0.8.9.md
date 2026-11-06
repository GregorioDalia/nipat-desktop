# Revisione scientifica 0.8.9

La 0.8.9 è una versione di sviluppo dedicata alle prestazioni del core R e
alla chiarezza della configurazione delle risorse. La versione ufficiale
rimane la 0.8.5. Il numero del pacchetto identifica il codice candidato;
non implica pubblicazione, accettazione o disponibilità nell'aggiornatore.

## Riferimento

Il riferimento è la release `v0.8.5`, commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`, comprese le modifiche di
compatibilità già distribuite. Le copie immutabili dei sei file R sono in
[`tests/reference_r/0.8.5`](https://github.com/GregorioDalia/nipat-desktop/tree/feature/0.8.9-r-optimization/tests/reference_r/0.8.5), con manifest
SHA-256. Il codice candidato rimane nelle normali directory del motore.
Le copie di riferimento sono usate soltanto dai test e non sono installate.

## Interventi

| Componente | Revisione |
| --- | --- |
| DNPcall | Raggruppamento unico delle osservazioni, indici delle righe per locus, eliminazione del conteggio Other duplicato e riduzione degli intermedi inutilizzati. |
| SNPcall | Raggruppamento unico per QNAME, esclusione anticipata dei nomi vuoti e riduzione delle conversioni e degli intermedi. |
| CPI | Calcolo unico per coppia e pannello, riutilizzo delle associazioni e dei valori per sito, accumulo dei risultati senza crescita ripetuta delle tabelle. |
| Contamination | Raccolta delle righe di riepilogo e assemblaggio finale unico. |
| Configurazione risorse | Distinzione fra configurazione salvata, risorse effettive, suggerimenti e nuovi limiti; Invio conserva le impostazioni correnti. |

Le formule, le soglie, l'accesso al BAM tramite samtools e i formati dei
risultati scientifici rimangono oggetto del contratto di equivalenza.
La revisione non introduce nuovi linguaggi o dipendenze R. Modifiche alla
politica di accesso indicizzato, elaborazione per blocchi, dimensioni dei
grafici e stime del tempo residuo richiedono verifiche distinte e non sono
implicite in queste ottimizzazioni.

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

Lo sviluppo procede su un branch separato. Push e pull request avviano i
controlli applicabili, senza modificare `Latest`, tag o asset della 0.8.5.
La pubblicazione richiede una decisione separata e un contratto di
accettazione che includa le nuove evidenze di equivalenza. I precedenti
record di accettazione rimangono riferiti esclusivamente ai propri artefatti.
