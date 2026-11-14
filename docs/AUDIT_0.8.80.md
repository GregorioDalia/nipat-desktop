# Consolidamento pre-GUI 0.8.80

La versione consolida i cinque moduli, i workflow composti, il menu guidato
e la CLI. Il perimetro comprende i rilievi residui dell'[audit
0.8.70](AUDIT_0.8.70.md) e le verifiche aggiuntive integrate con la
[PR #46](https://github.com/GregorioDalia/nipat-desktop/pull/46).

## Interventi e verifiche

| Area | Correzione | Verifica pertinente |
| --- | --- | --- |
| Identità dei contig e input BAM | SNP conserva i contig testuali. I caller verificano contig, lunghezze e compatibilità dei dizionari BAM rispetto al riferimento e ai marcatori. | Identificatori `01`, `1`, `NA`, contig mancanti, dizionari incompatibili e casi ordinari con samtools/R. |
| Riepilogo DNP | I genotipi complessivi devono concordare con tutte le tabelle individuali. | Alterazioni del riepilogo, campioni/loci mancanti e output validi. |
| D7, D8: piano ed esiti | Form, riepilogo e compilatore concordano sui rami e ruoli attivi. I lettori condividono il record finale dopo i controlli sugli input. | Importazioni asimmetriche, rami inattivi, ruoli familiari, record grandi e fallimento del controllo finale. |
| D6: preferenze | Salvataggio coordinato fra processi, unione delle modifiche indipendenti e diagnosi dei conflitti. | Due sessioni con modifiche distinte o concorrenti sullo stesso campo. |
| D10: CLI | Codice 2 per riavvio/verifica richiesti incompleti e arresto con pulizia incompleta. | Riavvio rinviato o fallito, risorse non confermate, container fermato ma non rimosso e successo completo. |
| D4: preparazione | Log durante i controlli, limiti distinti per diagnostica e autotest, errore riprendibile. Nessun limite aggiunto ai run scientifici o al menu. | Controllo bloccato, output prima dell'uscita, arresto del solo processo controllato e ripresa. |
| D5: aggiornamento Ubuntu | Conferma di avvio separata dall'hash del DEB, verifica integrale prima di APT. | Lettura lenta, pacchetto modificato, annullamento durante la verifica e terminale non avviato. |
| D9: guida | Descrizione dei workflow completi e canale coerente con versione e preferenze. | Consultazione con versione stabile/prerelease e canale Stabile/Testing senza avviare aggiornamenti o analisi. |

I test pertinenti vengono eseguiti dalla CI e dalla build candidata. I
rapporti della pubblicazione e `desktop-acceptance.json` identificano
l'esatto commit, i pacchetti e le verifiche completate.

## Ambito delle evidenze

Le prove Windows e le misure sui file reali riportate nell'audit 0.8.70
restano evidenze storiche della versione effettivamente provata. Il confronto
della 0.8.80 installata sugli stessi dati deve registrare input, parametri,
tabelle, tempi per fase e memoria secondo il [protocollo](PERFORMANCE.md).
La corretta conclusione di un run non dimostra da sola la parità numerica.

La distribuzione segue i [criteri pre-1.0](ACCETTAZIONE_INSTALLATORI.md):
gli scenari desktop non eseguiti, comprese le VM macOS reali quando assenti,
rimangono dichiarati come tali. La validazione di dominio conserva il proprio
ambito separato. L'ottimizzazione ulteriore dei blocchi DNP e dell'avvio
richiede misure dedicate e non introduce nuove funzionalità in questa release.

## Base per l'interfaccia grafica

Input, parametri, risultati e stati dei workflow costituiscono il riferimento
per la GUI. Correzioni successive mantengono versioni e note di rilascio
distinte, senza sovrascrivere i pacchetti già pubblicati.
