# NIPAT Desktop 0.8.70

Scaricare `NIPAT-Setup.exe` per Windows, il pacchetto DEB per Ubuntu 24.04 o il PKG macOS dell'architettura del computer. Le [guide di installazione](README.md#installare) descrivono requisiti, aggiornamento e verifica.

## Risultati e input

- DNPcall e SNPcall conservano contig e nomi di lettura come testo. Gli identificatori `01` e `1` restano distinti anche nei join di Contamination, CPI prenatale e CPIN postnatale.
- I caller segnalano REF discordanti nel pileup. In modalità BAM verificano che le finestre dei marcatori rientrino nel riferimento indicizzato. Un campione DNP senza copertura conserva i loci a conteggi zero e genotipo non assegnato. SNPcall respinge i QNAME ripetuti nella stessa posizione utile perché il pileup non distingue i mate.
- CPI prenatale calcola direttamente il log10 dell'indice combinato. Per prodotti fuori dall'intervallo numerico, il CPI grezzo può risultare 0 o infinito mentre il valore logaritmico resta disponibile. CPI e CPIN rifiutano totali incoerenti con i conteggi. Contamination ricava il rapporto REF dai conteggi osservati.
- Le verifiche dei risultati includono gli alleli delle tabelle DNP e la presenza delle curve CPI per ogni coppia e pannello.

## Installazione e prestazioni

- Il setup e il collaudo Windows ricavano la versione dalla build. L'aggiornamento riconosce il codice di riavvio richiesto. Gli hook Ubuntu della versione ripristinata chiudono lo stato di manutenzione dopo un rollback completato da dpkg.
- DNPcall indicizza il pileup con tipi espliciti e riconosce duplicati BAM in un passaggio. Il batch SNP salva lo stato alle transizioni. Le misure Windows sui file reali nell'[audit](AUDIT_0.8.70.md#benchmark-sul-client-windows-0860) sono il riferimento per misurare il guadagno end-to-end.
- GitHub può avviare prima le prove scientifiche e mette in coda le sole pubblicazioni autorizzate da un record di accettazione. L'[audit tecnico](AUDIT_0.8.70.md) riporta i casi esaminati e le priorità rimaste.

## Verificare l'installazione

La [guida al collaudo Windows](COLLAUDO_INSTALLAZIONE.md) esegue i cinque moduli con dati sintetici e conserva i rapporti sul computer. Per i flussi su dati rappresentativi, seguire la [procedura di validazione tecnico-scientifica](VALIDAZIONE.md).
