"""Presentation-only messages shared by CLI diagnostics and future interfaces.

The existing guided forms remain Italian. This initial catalog covers reliability
diagnostics; language never changes command names, JSON keys or scientific values.
"""
from __future__ import annotations

MESSAGES = {
    "it": {
        "run_failed": "Esecuzione non riuscita: {path}",
        "failed_results": "La voce 6 permette di consultare i log e gli eventuali risultati parziali di questa esecuzione.",
        "no_session_runs": "Nessuna esecuzione registrata in questa sessione.",
        "recovery_title": "Esecuzioni incomplete",
        "recovery_help": "Il controllo confronta i record conservati con i container dell'ambiente corrente. Non riprende i calcoli e non elimina risultati.",
        "no_incomplete_runs": "Nessuna esecuzione incompleta trovata nella cartella risultati.",
        "run_name": "Esecuzione: {name}",
        "recorded_status": "Stato registrato: {status}",
        "backend_match": "Corrispondenza con l'ambiente corrente: {matches}",
        "container_status": "Container {name}: {state}; proprieta' verificata: {owned}",
        "no_containers": "Il record non identifica container da controllare.",
        "recovery_error": "Dettaglio: {error}",
        "stop_confirm": "Arrestare i container verificati di questa esecuzione? [s/N]",
        "stop_cancelled": "Arresto annullato. Nessuna richiesta di arresto inviata.",
        "stop_requested": "Richiesta di arresto elaborata. Verificare gli esiti dei container e recovery.json; i risultati sono conservati.",
        "yes": "si", "no": "no",
    },
    "en": {
        "run_failed": "Run failed: {path}",
        "failed_results": "Option 6 opens this run's logs and any partial results.",
        "no_session_runs": "No run has been recorded in this session.",
        "recovery_title": "Incomplete runs",
        "recovery_help": "Inspection compares saved records with containers in the current runtime. It does not resume calculations or delete results.",
        "no_incomplete_runs": "No incomplete run was found in the results directory.",
        "run_name": "Run: {name}",
        "recorded_status": "Recorded status: {status}",
        "backend_match": "Matches the current runtime: {matches}",
        "container_status": "Container {name}: {state}; verified ownership: {owned}",
        "no_containers": "The record does not identify any container to inspect.",
        "recovery_error": "Details: {error}",
        "stop_confirm": "Stop this run's verified containers? [y/N]",
        "stop_cancelled": "Stop cancelled. No stop request was sent.",
        "stop_requested": "Stop request processed. Check the container outcomes and recovery.json; results are preserved.",
        "yes": "yes", "no": "no",
    },
}


def translate(key: str, language: str = "it", **values: object) -> str:
    """Translate an explicit message identifier, never scientific payloads."""
    return MESSAGES[language][key].format(**values)
