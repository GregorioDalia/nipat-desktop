# NIPAT: stato del progetto e funzionamento

**Versione CLI 0.2.0a1, destinata alla validazione con l'esperta di dominio.**
NIPAT riunisce quattro analisi in un unico strumento locale. Python gestisce
file, controlli ed esecuzioni; i calcoli sono affidati agli script R di DNPcall
e NEWPAT, eseguiti insieme a samtools in Docker. La GUI verrà dopo questa fase.

## Che cosa è integrato

| Analisi | Input principali | Risultati |
| --- | --- | --- |
| DNPcall | BAM con indice, riferimento FASTA con indice, pannello DNP | Conteggi e genotipi per sito, riepiloghi e grafici. |
| SNPcall | BAM e riferimento indicizzati, lista SNP | Generazione automatica del pileup e tabella dei conteggi SNP. |
| Contamination | Tabelle DNPcall e pannello DNP | Stima per sito e riepilogo per campione. |
| CPI | Tabelle cfDNA materno/presunto padre, coppie da confrontare, frequenze di popolazione e pannello opzionale | Frazione fetale, CPI e grafici. |

## Che cosa è stato fatto

Sono stati corretti i problemi di compatibilità di DNPcall con un solo campione
e con i percorsi di output. CPI e Contamination sono stati aggiornati alla
versione NEWPAT acquisita il 19 ottobre 2026. Contamination accetta direttamente
i conteggi di DNPcall e calcola `ratio_REF_ALT = N_REF / (N_REF + N_ALT)`
quando assente.

I controlli già eseguiti comprendono un campione reale DNPcall, il passaggio
del suo output a Contamination, un campione reale SNPcall e la corrispondenza
dell'esempio SNPcall con il riferimento degli autori. I test sintetici CPI e
Contamination verificano valori attesi e casi senza siti informativi.
Queste verifiche tecniche precedono la validazione scientifica su altri input.

## Come si usa

Su Windows a 64 bit, si scarica ed estrae da GitHub la versione indicata per
la validazione. Serve Docker Desktop avviato in modalità container Linux.
`1_SETUP.cmd` scarica Python locale, prepara il runtime scientifico ed esegue
gli autotest; `2_AVVIA.cmd` apre la procedura guidata testuale. Il primo setup
richiede Internet. Rimangono disponibili anche i comandi CLI diretti.

Gli input si collocano nella cartella `data` accanto al progetto. Ogni analisi
crea una nuova cartella in `runs`, con risultati, file intermedi, `run.json`
e `execution.log`. I metadati registrano input, parametri, versioni ed esito;
il log conserva comandi e messaggi. Il progetto e `data` sono montati in sola
lettura; `runs` è scrivibile e i run esistenti non vengono sovrascritti.
Durante le analisi i dati
restano sul computer; l'installazione può richiedere download.

Per cominciare: [guida della collega](docs/GUIDA_COLLEGA.md).
Per riportare le prove: [scheda di validazione](docs/VALIDAZIONE.md).
