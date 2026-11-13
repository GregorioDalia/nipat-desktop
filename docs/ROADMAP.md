# Sviluppo e validazione

Le priorità di sviluppo riguardano la correttezza dei risultati, la ripetibilità delle analisi e l'utilizzo sui dispositivi supportati. Il comportamento corrente è descritto nell'[indice delle guide](https://github.com/GregorioDalia/nipat-desktop/blob/main/docs/README.md). Le decisioni e le prove delle singole versioni sono nell'[archivio](https://github.com/GregorioDalia/nipat-desktop/blob/main/docs/archive/README.md).

## Priorità

| Area | Obiettivo verificabile |
| --- | --- |
| Validazione di dominio | Valutare casi rappresentativi usando parametri dichiarati, risultati di riferimento e criteri concordati con chi esegue le analisi scientifiche. |
| Affidabilità dei workflow | Verificare legame fra campioni, ruoli familiari, parametri effettivi e risultati, anche dopo errori e annullamenti. |
| Prestazioni | Confrontare tempi, picchi di memoria e worker osservati con input e risorse controllati. Misurare separatamente pileup, calcolo R e orchestrazione. |
| Piattaforme | Qualificare installazione, avvio, recupero e aggiornamento su Windows 10/11, Ubuntu e macOS Intel/Apple Silicon. |
| Usabilità | Rendere leggibili avanzamento, riepilogo dei parametri, avvisi e diagnostica. Provare i percorsi d'uso su dispositivi reali. |
| Interfaccia grafica | Riutilizzare contratti del client ed eventi di avanzamento. Valutare la visualizzazione locale dei dati come funzione distinta dell'interfaccia. |
| Localizzazione | Estendere italiano e inglese senza duplicare regole e controlli applicativi. |

## Metodo di verifica

- **Modelli scientifici.** Usare [sorgenti di riferimento congelati](../scientific/README.md#provenienza-e-identità), oracoli analitici e casi limite. Documentare eventuali modifiche a formule, soglie o filtri come cambiamenti di modello.
- **Prestazioni.** Applicare il [protocollo di misura](PERFORMANCE.md) e verificare la concordanza numerica prima di attribuire un miglioramento di velocità a un cambiamento.
- **Pacchetti.** Collegare l'evidenza al commit, all'immagine e al pacchetto effettivo. Registrare esiti automatici e osservazioni sui dispositivi con il [protocollo di accettazione](ACCETTAZIONE_INSTALLATORI.md).
- **Segnalazioni.** Nella [scheda di validazione](VALIDAZIONE.md) indicare versione, ambiente, risultato atteso e risultato osservato. Ridurre il caso a input condivisibili quando possibile.
