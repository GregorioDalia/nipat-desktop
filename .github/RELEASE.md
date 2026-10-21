# Pubblicazione dell'installatore verificato

Il workflow **Publish verified Windows pre-release** trasferisce gli asset da
una build riuscita a GitHub Releases senza ricompilarli o scaricarli sul PC
del manutentore. Si avvia manualmente da Actions sul branch `main`, indicando
l'ID della build **Windows installer (review build)** e il suo commit completo.
Il commit deve essere già integrato in `main`.

La procedura verifica build, manifest, sorgenti, archivi e checksum, crea una
bozza sul commit compilato e carica EXE, due archivi, manifest e `SHA256SUMS`
combinato. Pubblica come pre-release solo dopo aver verificato dimensioni e
digest degli asset caricati. Non modifica release già pubblicate né tag di
altri commit; una bozza parziale può essere ripresa solo con gli stessi
contenuti verificati. Un errore lascia la bozza non pubblicata.
Per riprendere una bozza già creata si può indicare il suo ID nel campo
facoltativo `draft_release_id`; commit, note e asset vengono comunque verificati.

Le note provengono da `docs/RELEASE_<versione>.md` del commit compilato.
I file di questa procedura sono strumenti del manutentore: non fanno parte
dei sorgenti applicativi inclusi nell'EXE e non richiedono di ricostruire un
runtime già verificato. Le prove su Windows e di dominio rimangono distinte
dai controlli di pubblicazione.
