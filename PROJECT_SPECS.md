# Specifiche Progetto: Custom Git Client GUI

## Obiettivo
Creare un'applicazione desktop in Python per Ubuntu che replichi le funzionalità core di GitKraken, con un'interfaccia simile, ma con un focus speciale su un sistema nativo di gestione multi-utente.

## Stack Tecnologico
- Linguaggio: Python 3.10+
- Interfaccia Grafica: PyQt6 (tema scuro di default)
- Core Git: GitPython
- Struttura: Model-View-Controller (MVC) o architettura modulare pulita.

## Requisiti UI (Layout Principale)
1. Sidebar Sinistra: Pannello per branch locali/remoti, tag e submodule.
2. Area Centrale: Grafo dei commit interattivo (nodi per i commit, linee per branch/merge).
3. Pannello Destro: Diviso in due. Sopra: Staging area (Staged/Unstaged files). Sotto: Diff viewer con syntax highlighting.
4. Top Toolbar: Pulsanti per Undo, Redo, Pull, Push, Branch, Stash, Pop.

## Funzionalità Multi-Utente (Priorità Alta)
- Implementare un "Profile Manager" accessibile dall'interfaccia.
- Gestione profili: creazione, salvataggio e switch tra profili.
- Ogni profilo salva: `user.name`, `user.email` e percorso chiave SSH/token.
- Al cambio profilo, l'app aggiorna la configurazione locale/globale di Git e l'ambiente di esecuzione (es. `GIT_SSH_COMMAND`) per evitare commit o push con credenziali errate.

## Regole di Sviluppo per l'Agente
- Lavora in modo incrementale seguendo la ROADMAP. Non scrivere tutto in un solo file.
- Scrivi codice pulito, ampiamente commentato e usa i type hints.
- Gestisci le dipendenze in un file `requirements.txt`.
- Dopo ogni fase completata, avvia il `main.py` per testare l'assenza di errori bloccanti nella GUI.

## Open Source & Community
- Licenza: MIT License.
- Documentazione Iniziale: Creare un `README.md` accattivante che spieghi la missione del progetto (alternativa FOSS nativa a GitKraken per Linux), lo stack usato e come avviare l'app.
- Contributi: Creare un file `CONTRIBUTING.md` per spiegare alla community come fare setup locale, inviare Pull Request e segnalare bug.
- Codice leggibile: Tutto il codice deve essere scritto pensando a futuri contributori (modulare, ben strutturato e commentato in modo chiaro).
