# Roadmap di Sviluppo (8 Fasi)

## Fase 1: Setup e Scheletro dell'Interfaccia (Foundation)
- Task 1: Inizializzare un ambiente virtuale (venv) e creare il `requirements.txt` (PyQt6, GitPython, Pygments).
- Task 2: Creare la struttura delle cartelle: `src/models/`, `src/views/`, `src/controllers/`, `src/utils/`.
- Task 3: Sviluppare il `main.py` e la `MainWindow` in PyQt6. Implementare il layout principale usando QSplitter: Left Sidebar (20%), Main Center (50%), Right Panel (30%).
- Task 4: Applicare un foglio di stile globale (QSS) per una dark mode moderna.

## Fase 2: Gestore Multi-Utente (Identity Manager)
- Task 1: Creare un modello dati (JSON locale, es. `profiles.json`) per memorizzare: Nome Profilo, `user.name`, `user.email`, Percorso Chiave SSH.
- Task 2: Creare una finestra di dialogo (QDialog) in PyQt6 per aggiungere, modificare o eliminare profili.
- Task 3: Implementare la logica nel Controller. Al cambio di profilo, usare GitPython per eseguire `git config user.name` e `user.email` sul repository corrente e impostare l'ambiente per usare la chiave SSH corretta (`GIT_SSH_COMMAND`).

## Fase 3: Apertura Repo e Barra Laterale (Sidebar)
- Task 1: Aggiungere un menu "File -> Open Repo / Init Repo / Clone Repo" e collegarli alle funzioni di GitPython.
- Task 2: Leggere i branch. Mostrare nella barra laterale sinistra una vista ad albero (QTreeView) divisa in: Local Branches, Remote Branches, Tags.
- Task 3: Permettere il doppio clic su un branch locale per fare il checkout (`git checkout`).

## Fase 4: Il Grafo dei Commit (The Canvas)
- Task 1: Creare una funzione che legga la cronologia dei commit (hash, autore, data, messaggio, parent_hashes) tramite GitPython.
- Task 2: Creare un widget custom (es. usando `QGraphicsView`/`QGraphicsScene`) per il pannello centrale.
- Task 3: Disegnare i nodi (pallini) e il testo (dettagli del commit).
- Task 4: Disegnare le linee di connessione calcolando branch e merge, assegnando colori diversi ai branch.

## Fase 5: Area di Staging (Working Directory)
- Task 1: Creare l'interfaccia nel pannello in alto a destra con due liste: "Unstaged Files" e "Staged Files".
- Task 2: Leggere lo stato del repo (`git status`) e popolare le liste.
- Task 3: Aggiungere pulsanti per fare lo stage/unstage. Collegare questi bottoni a `git add` e `git reset`.
- Task 4: Aggiungere un campo di testo per il messaggio di commit e un bottone "Commit", collegato a `git commit` (usando le credenziali del profilo attivo).

## Fase 6: Visualizzatore Diff (Diff Viewer)
- Task 1: Al clic su un file nella Staging Area o nel Grafo, generare il diff testuale tramite GitPython.
- Task 2: Visualizzare il diff in un `QTextEdit` nel pannello in basso a destra.
- Task 3: Applicare syntax highlighting (es. Pygments) con sfondo rosso per righe eliminate (`-`) e verde per righe aggiunte (`+`).

## Fase 7: Azioni Core (Toolbar e Sync)
- Task 1: Creare i bottoni nella barra superiore (Fetch, Pull, Push, Branch, Stash, Pop).
- Task 2: Implementare la logica di rete. L'autenticazione deve passare correttamente tramite la chiave SSH del profilo attivo.
- Task 3: Aggiungere indicatori di caricamento e popup d'errore (es. QMessageBox) per problemi di rete o conflitti.

## Fase 8: Rifiniture, Merge e Conflitti (Advanced)
- Task 1: Supportare il merging tramite drag & drop (trascinare un branch sopra un altro nel pannello sinistro).
- Task 2: Rilevare i conflitti di merge. Mostrare un avviso chiaro e permettere di annullare (`git merge --abort`).
- Task 3: Ottimizzare le performance del grafo dei commit implementando paginazione o lazy loading.

## Fase 9: UI Revamp (Icone, Menu e Context Menus)
- Task 1: Aggiungere `qtawesome` a `requirements.txt` e installarlo nell'ambiente virtuale.
- Task 2: Sostituire i testi dei bottoni nella Toolbar e nell'interfaccia con icone moderne usando `qtawesome` (mantenere tooltip con testo).
- Task 3: Abilitare il Menu Contestuale (tasto destro) nella Sidebar: su un branch locale → Checkout, Delete Branch, Rename Branch; su un branch remoto → nessuna azione distruttiva.
- Task 4: Abilitare il Menu Contestuale nel Grafo dei Commit: clic destro su una riga → Checkout this commit (detached HEAD), Copy Hash.
- Task 5: Completare la barra dei menu aggiungendo: `Settings` (placeholder per future preferenze) e `Help` → `About` (versione, autori, licenza) + `Useful Links` (repo GitHub).

## Fase 10: Gestione Repository e Configurazione Globale
- Task 1: Creare un `RepositoryManager` che memorizzi in un JSON (`~/.config/ubuntu-gitgui/recent_repos.json`) gli ultimi N repository aperti (path, nome, ultima apertura).
- Task 2: Aggiungere un menu `Recent Repositories` nel menu File e un'eventuale schermata Home per ricaricare un repo con un clic.
- Task 3: All'avvio, leggere `~/.gitconfig` globale (via GitPython o parsing diretto) e creare automaticamente un profilo non cancellabile `System Default` con quelle credenziali, usato come fallback se nessun profilo è attivo.

## Fase 11: Commit Inspector
- Task 1: Implementare un evento al clic su una riga nel Grafo dei Commit.
- Task 2: Al clic, nascondere temporaneamente l'area di Staging e mostrare il `CommitInspectorWidget`: hash completo, autore, data, messaggio esteso, lista dei file modificati da quel commit.
- Task 3: Al clic su un file nella lista del Commit Inspector, il Diff Viewer deve mostrare il diff di quel file per quel preciso commit (`git show <hash> -- <file>`).
- Task 4: Aggiungere un pulsante per tornare alla vista normale (Staging Area).

## Fase 12: Multi-Repository Manager
- Task 1: Creare un `RecentRepositoryManager` che salvi in `~/.config/ubuntu-gitgui/recent_repos.json` gli ultimi N repository aperti (path, nome, data ultima apertura).
- Task 2: Aggiungere un sottomenu `Recent Repositories` nel menu File, popolato dinamicamente, che permetta di riaprire un repo con un clic.
- Task 3: Implementare una schermata Home (mostrata all'avvio se nessun repo è aperto) con una lista grafica dei repo recenti, con anteprima del nome, path e branch attivo.
- Task 4: Supporto opzionale per aprire più finestre indipendenti (`QMainWindow` separate) su repository diversi contemporaneamente.

## Fase 13: Impostazioni Avanzate e Localizzazione (i18n)
- Task 1: Creare una schermata Settings completa accessibile dal menu Settings → Preferences: tema (dark/light/system), font size, lingua, numero massimo di commit caricati per pagina.
- Task 2: Implementare il supporto multilingua (i18n) usando `gettext` o `Qt Linguist` (`.ts`/`.qm`). Lingue iniziali: Italiano e Inglese.
- Task 3: Persistere le preferenze in `~/.config/ubuntu-gitgui/settings.json` con lettura all'avvio e applicazione dinamica (cambio tema/font senza riavvio).
- Task 4: Aggiungere un tema Light Mode alternativo al QSS attuale e un selettore in Settings.

## Fase 14: Packaging e Build Script
- Task 1: Aggiungere `pyinstaller>=6.0` a `requirements.txt`.
- Task 2: Creare `build.sh`: script che usa PyInstaller `--onedir` per compilare l'app in un bundle Linux autonomo (`dist/ubuntu-gitgui/`). Include `src/locales`, `src/styles` e `qtawesome` come data files.
- Task 3: Creare `ubuntu-gitgui.desktop` per integrare l'app nel launcher di sistema (GNOME/KDE).
- Task 4: Aggiornare `README.md` con la sezione "How to Build".

## Fase 15: Gestione Completa dei Tag (Tag Management)
- Task 1: **Sidebar** — popolare correttamente la sezione Tags da `repo.tags`; doppio clic su un tag esegue il checkout in stato detached HEAD con warning preventivo (QMessageBox).
- Task 2: **Creazione Tag dal Grafo** — menu contestuale (tasto destro) sul grafo dei commit → "Create Tag Here…": dialog custom con nome + messaggio opzionale; crea il tag con `repo.create_tag()` e aggiorna sidebar.
- Task 3: **Eliminazione Tag dalla Sidebar** — context menu sul tag → "Delete Tag…" con conferma; usa `repo.delete_tag()`.
- Task 4: **Push Tag dalla Sidebar** — context menu → "Push Tag to Remote": usa il profilo SSH attivo (`GIT_SSH_COMMAND`) e `git push origin refs/tags/<nome>`.
- Task 5: **Badge Tag nel Grafo** — se un commit ha tag associati, mostra `[tag_name]` come prefisso nella colonna Message del grafo, così le release sono immediatamente visibili.
