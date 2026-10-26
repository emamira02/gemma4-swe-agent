"""Assemble the technical deep-dive (agent versions S1..Sn + paper) from the real artefacts.

    python tools/tech_report.py [--out ../TECH_DEEP_DIVE_<date>.md]

Narrative sections live in this file; everything else is copied verbatim from the repository: the frozen bundles in
candidates/<TAG>/bundle (prompts, configs, scripts), unified diffs between consecutive versions, dev-panel metrics
(results/agent_runs/*.json), leaderboard scores (runs.csv), the LLM prompts (analysis/llm_v2.py), the paper
(paper/PAPER.md) and its generated tables (paper/RESULTS.md, paper/RESULTS_LLM.md, paper/RESULTS_AGENT.md), the
failure audit (results/failure_audit.json) and the Linux editor check (results/editor_check/). No competition data
is included.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAND = ROOT / "candidates"
LANG = {".py": "python", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown", ".json": "json"}

INTRO = """# DEEP DIVE TECNICO — Agente Kaggle (versioni {first}–{last}) e paper "Anchors Decide"
Generato automaticamente il {date} da `tools/tech_report.py` nel repository pubblico
https://github.com/emamira02/gemma4-swe-agent (pubblico dal 26/10/2026).
Le parti narrative sono scritte a mano; prompt, configurazioni, codice, differenze tra versioni, metriche e paper
sono copiati alla lettera dai file reali (versioni congelate in `candidates/<TAG>/bundle`). Nessun dato della
competizione (testi delle issue, patch) è incluso. Da leggere insieme a HANDOFF_2026-10-26.md.

Indice
1. Il problema e i vincoli dell'harness
2. Come gira un task (dal container alla verifica)
3. Architettura dell'agente e perché è fatta così
4. I componenti, uno per uno
5. Come si sviluppa, si valuta e si invia una versione (metodo)
6. Versione per versione: {tags} (motivazione, modifiche, risultati, decisione) + S6 in dettaglio
7. Il paper: domanda, dati, metodo, statistica, risultati, garanzie di rigore
8. Appendice A — bundle completo dell'ultima versione (testo esatto)
9. Appendice B — differenze esatte tra versioni consecutive
10. Appendice C — paper completo e tabelle dei risultati generate
"""

SEC1 = """## 1. Il problema e i vincoli dell'harness
- Compito: dato il testo di una issue GitHub e il repository Python al commit base, produrre una patch che faccia
  passare i test nascosti scritti dai maintainer per quella issue (stile SWE-bench). Tutti i test devono passare,
  nessun credito parziale; patch vuota = 0.
- Si consegna una configurazione dichiarativa Google ADK (agent.yaml + prompt + skill + opzionali sub-agent e
  adapter LoRA), non codice Python libero. Gli script delle skill girano dentro il container del task.
- Modello unico obbligatorio: gemma-4-31b-it-qat-w4a16-ct (Gemma 4 31B quantizzato W4A16) servito da vLLM su
  4 GPU NVIDIA L4 (tensor parallel 4), contesto massimo 32.768 token, parser di tool e di ragionamento "gemma4",
  thinking attivo di default. Offline.
- Strumenti forniti dall'harness: run_command (bash in /workspace, output troncato a 5.000 caratteri, timeout
  per comando configurabile), read_file (al massimo 150 righe e 10.000 caratteri per chiamata), edit_file
  (sostituzione old_string → new_string con 3 livelli di matching: esatto, per righe senza spazi, regex
  tollerante), write_file, submit_patch (cattura git diff, gratuito), get_status (gratuito), e tre tool di
  "code intelligence" su grafo ed embedding precalcolati (search_similar_code, get_code_neighbors,
  get_code_subgraph). Più i tool delle skill: list_skills, load_skill, load_skill_resource, run_skill_script.
- Limite globale: 12 ore per circa 120 task nascosti, eseguiti uno alla volta, incluso il setup (~0,5 minuti per
  task). Sforare = intera submission in errore. Da qui il budget di 5 minuti per task.
- Compattazione automatica del contesto (ADK events compaction) oltre ~14k token.
- Il diff finale è quello del working tree: se il tempo scade, viene valutato lo stato corrente dei file (le
  modifiche fatte prima della scadenza non vanno perse). Le modifiche a file di test e di configurazione dei test
  vengono annullate dal valutatore prima di applicare i test nascosti.
- Classifica pubblica = ~58 task; finale = gli altri ~58 con le 2 submission scelte. 1 invio al giorno, uno solo
  in sospeso; ~2 giorni tra invio e punteggio (coda + esecuzione).
"""

SEC2 = """## 2. Come gira un task (ciclo di vita reale, letto nel codice dell'harness swegemma 0.2.11)
1. Container A: estrazione del repository al commit base, installazione editable, dipendenze di test,
   pytest.ini/conftest.py dell'harness, commit "baseline".
2. Compilazione della submission (adk_submission.compile_submission) in un albero di agenti ADK; i tool sono
   risolti per nome da un registro chiuso; le skill diventano un SkillToolset.
3. Messaggio utente iniziale costruito dall'harness: testo della issue, eventuali hint, budget (minuti, chiamate,
   turni), regole dell'ambiente, 6 istruzioni standard, albero delle cartelle (prime 150 voci). Il nostro
   prompt di sistema è l'"instruction" dell'agente.
4. Ciclo: il modello chiama tool; se un turno finisce senza tool e senza submit_patch, l'harness manda fino a 3
   "nudge" per continuare. Si termina con submit_patch + risposta testuale, oppure a budget esaurito.
5. run_skill_script: ADK scrive uno script "auto-estraente" che materializza i file della skill in una cartella
   temporanea, fa chdir lì e lancia lo script con python3 dentro il container. Per questo i nostri script
   cercano la root del repository da PWD/PYTHONPATH/"/workspace" e non dalla cartella corrente.
6. Estrazione della patch (git add -N . && git diff) e verifica in un container B pulito: applicazione della
   patch, reset dei file di test toccati, applicazione dei test nascosti, pytest con JUnit XML. Risolto solo se
   exit code 0 e tutti i test richiesti passano.
"""

SEC3 = """## 3. Architettura dell'agente e perché è fatta così
Scelta: UN solo LlmAgent, strumenti dell'harness essenziali + una skill "swe" con script deterministici. Niente
sub-agent, niente tool di grafo. S1–S5 usano run_command, read_file, edit_file, write_file, get_status,
submit_patch; da S6 edit_file e write_file sono tolti: le modifiche passano da run_command con l'editor della skill
(sezione 6.1), perché le chiamate con due argomenti di codice si rompono nel formato di chiamata del modello.
Motivazioni (con evidenza):
- Tempo: ogni chiamata al modello costa ~4–10 s (fino a ~60 s se il thinking arriva al limite). In 5 minuti ci
  stanno ~20–30 passi. Un sub-agent aggiunge passi e contesto; ablation pubbliche: +1 task su 129 (rumore).
- Tool di grafo: le ricerche semantiche risolvono la query solo su nomi di simboli; ablation pubbliche: nessun
  beneficio; il nostro studio (paper) mostra che senza ancore questi segnali crollano.
- Localizzazione: il nostro studio mostra che (a) identificatori + BM25 con regola di modalità sono il segnale
  migliore disponibile dentro il container, (b) il modello è molto bravo a RIORDINARE una lista di candidati.
  Quindi uno script deterministico produce la lista (1 chiamata, ~1 s) e il modello fa da re-ranker.
- Igiene della patch: uno script annulla modifiche a test/configurazioni, rimuove file temporanei e verifica la
  sintassi prima dell'invio (gli errori di sintassi o i file sporchi costano task).
- Prompt: procedura rigida a passi con limiti numerici (letture prima della modifica, modifica entro la
  6ª chiamata), perché le tracce mostravano esplorazione eccessiva e modifiche tardive.
"""

SEC4 = """## 4. I componenti, uno per uno (il testo esatto è nell'Appendice A)
- agent.yaml: un LlmAgent "swe_agent", modello gemma-4-31b-it-qat-w4a16-ct, instruction = prompts/system.md,
  tool dell'harness elencati sopra, skills: [skills/swe], generate_content_config = configs/sampling.yaml.
- configs/sampling.yaml: temperature 1.0, top_p 0.95 (raccomandazione Gemma; temperature 0.4 e 1.0 alla pari in
  ablation pubbliche), max_output_tokens 8192, thinking attivo con include_thoughts true (disattivarlo dimezza i
  risultati in ablation pubbliche), thinking_budget 2048 (S1–S3) poi 1024 (S4–S5). Niente thinking_level (su vLLM
  diventa reasoning_effort) e niente top_k (LiteLLM lo scarta per endpoint OpenAI-compatibili).
- eval_config.yaml: max_time_minutes 5.0, timeout_seconds 100 (per comando), max_tool_calls 40 (S1) poi 32 (da S2:
  l'harness aggiunge un avviso "finalizza" a ogni risultato quando ne restano ≤10), max_turns 60. Caso peggiore
  120 × (5,0 + 0,5) min + setup ≈ 11,25 h (il builder rifiuta configurazioni oltre 11,5 h).
- skills/swe/SKILL.md: descrive gli script; il prompt dice di NON chiamare load_skill (risparmia una chiamata).
- skills/swe/scripts/localize.py (solo libreria standard, sola lettura):
  1. trova la root del repository (PWD, PYTHONPATH, /workspace; --root esplicito vince);
  2. elenca i .py con git ls-files (fallback os.walk), salta cartelle di build/venv/cache;
  3. separa i test (non sono mai candidati alla modifica, servono solo a suggerire "RELATED TESTS");
  4. analizza ogni file con ast: funzioni, classi, metodi (range di righe inclusi i decoratori, firma, prima
     riga della docstring); per le classi indicizza intestazione + nomi dei metodi; il codice a livello di modulo
     diventa un simbolo "<module>"; file non analizzabili diventano un simbolo unico;
  5. tre segnali: (a) identificatori estratti dalla query (backtick, nomi puntati, CamelCase, snake_case,
     chiamate, frame di traceback, percorsi di file) risolti come fa l'harness: esatto → suffisso puntato →
     case-insensitive → sottostringa, con pesi 1,0/0,8/0,5/0,2; (b) BM25 (k1 1,2, b 0,75) su token del nome
     (peso doppio) + sorgente; (c) frasi citate e messaggi di errore cercati letteralmente nel sorgente;
  6. regola di modalità del paper: se almeno un identificatore si risolve ("anchored") fonde le liste con
     reciprocal-rank fusion (k = 60); altrimenti ("lexical") usa solo BM25 + letterali; i file di docs/esempi
     pesano la metà;
  7. stampa: modalità, i primi 30 simboli come path:prima-ultima riga, nome, firma, docstring; i file
     principali; le corrispondenze letterali; i file di test correlati con il comando pytest suggerito; da S3, in
     modalità anchored, anche il codice esatto del simbolo #1 (se ≤ 80 righe) per modificarlo senza rileggerlo.
  Parità verificata con i test: tokenizzazione, estrazione identificatori e BM25 identici al codice dello studio.
  Valutazione offline sui 114 task: questa politica raggiunge R@5 34,2% e R@50 70,2% sui simboli corretti.
- skills/swe/scripts/finalize.py: legge git status; ripristina con git checkout i file protetti modificati
  (test, conftest.py, pytest.ini, pyproject.toml, setup.cfg, tox.ini, ...) e cancella quelli nuovi; cancella file
  temporanei alla radice (repro*, debug*, tmp*, ...), *.orig/*.rej e (da S3) tutto ciò che sta in /workspace/tmp;
  compila in memoria ogni .py modificato e segnala errori di sintassi (exit 1); avvisa se la patch è vuota;
  stampa git diff --stat e "OK: call submit_patch now".
- skills/swe/scripts/replace_lines.py (solo S5): alternativa a edit_file quando le chiamate si rompono: il modello
  scrive le righe nuove con write_file in tmp_new_lines.txt e poi sostituisce le righe A–B per numero; il
  risultato viene applicato solo se il file compila; stampa le righe rimosse e la nuova regione numerata.
  Rimosso in S6 (sostituito da edit.py, che ha anche la modalità per intervallo di righe).
- skills/swe/scripts/edit.py (da S6): l'editor dei file, chiamato con run_command e un heredoc; descritto per
  intero nella sezione 6.1. localize.py lo copia in /tmp/swe/edit.py (finalize.py lo reinstalla se la patch è
  vuota), perché la cartella in cui run_skill_script materializza gli script viene cancellata a fine chiamata.
- prompts/system.md: sezioni HOW TO CALL TOOLS (argomenti come campi separati con valori semplici, mai backtick),
  STEPS con limiti duri (1 localizza; 2 scegli/riordina; 3 al massimo 3 letture prima della modifica; 4 modifica
  entro la 6ª chiamata con old_string di 2–8 righe esatte, mai triple virgolette; 5 al massimo 2 verifiche
  mirate solo se restano ≥ 90 s; 6 finalize poi submit_patch e una frase), RULES (mai test/config, write_file
  scrive sempre in /workspace, niente refactoring, niente pip, mai ripetere una chiamata fallita identica, issue
  vaghe: correzione minima più plausibile, mai finire senza modifica; da S4 "pensa poco e agisci"; da S5 regola
  di recupero per edit_file rotti). In S6 il passo 4 insegna l'editor con un esempio completo di heredoc, la regola
  sui valori diventa "mai racchiudere un valore tra backtick o virgolette" (il comando dell'editor contiene
  legittimamente 'EOF'), la regola write_file diventa "file temporanei solo in /tmp o python -c" e la regola di
  recupero dice cosa fare se l'editor stampa EDIT NOT APPLIED o "No such file".
"""

SEC5 = """## 5. Metodo: sviluppo, valutazione, invio
- Build (tools/build_submission.py): copia pulita del bundle; validazione dura (una sola root config, estensioni
  ammesse, niente symlink/cache, include risolti, un solo modello ed è quello della gara, chiavi di sampling
  ammesse e nei limiti, frontmatter delle skill, budget 12 h); compilazione con le librerie ufficiali
  dell'harness (adk_submission 0.2.13, google-adk 1.36.1, swegemma 0.2.11 in un venv Python 3.13, come il
  container); zip riproducibile byte per byte (timestamp fissi, fine riga LF); notebook CPU che scrive lo zip.
- Congelamento: candidates/<TAG>/bundle + MANIFEST.json con sha256; un tag già congelato non può cambiare;
  l'invio usa sempre la copia congelata e verifica che lo zip prodotto da Kaggle abbia lo stesso hash.
- Prova interna ("pannello"): kernel Kaggle GPU (kernels/agent_eval) che riproduce lo scorer (4×L4, vLLM con le
  stesse impostazioni, task in sequenza, budget dall'eval_config del bundle) su 24 task pubblici del repository
  rich scelti con seed 0: {panel}. Per ogni task esegue anche la patch di riferimento per sapere se il task è
  risolvibile in questo ambiente (21–22 su 24). ~2 ore di GPU.
- Metriche dalle tracce (analysis/agent_traces.py): resolved_on_solvable (risolti tra i risolvibili), timeouts
  (sessioni arrivate al limite di 5 minuti), empty_patch (patch vuota), no_edit (nessuna chiamata di modifica),
  tasks_with_arg_errors (task con almeno una chiamata malformata: INVALID_ARGUMENTS, FileReadError,
  "mandatory input parameters are not present"), backtick_args, identical_repeat (stessa chiamata ripetuta),
  first_edit_s (secondi alla prima modifica).
- Regola di decisione scritta PRIMA della prova (RESUME.md): una versione diventa READY solo se risolve almeno
  quanto la migliore finora e non introduce un nuovo tipo di errore; altrimenti BLOCKED. Le READY vengono inviate
  dall'attività kaggle-loop (la migliore sul pannello, la più recente a parità) quando non c'è nulla in sospeso.
- Audit dei fallimenti (analysis/failure_audit.py, da S6): per ogni task e versione una categoria, la prima che si
  applica: GOLD_UNSOLVABLE (la patch di riferimento non passa), RESOLVED, NO_EDIT_TOOL (nessuna scrittura riuscita
  su un sorgente e ≥ 2 tentativi di modifica falliti a livello di tool), NO_EDIT, WRONG_FILE (scritto solo su file
  che la patch di riferimento non tocca), RIGHT_FILE_TIMEOUT, RIGHT_FILE_WRONG_FIX; più il rango del file giusto
  nell'output di localize e, per ogni tool, chiamate totali e malformate (chiavi inattese o obbligatorie mancanti).
  Output senza testo dei task: solo id, booleani e conteggi.
- Verifica Linux dell'editor (kernels/editor_check, da S6): kernel Kaggle solo CPU, gratuito, che riproduce la
  catena di esecuzione dell'harness e i casi limite dell'editor (sezione 6.1).
- Il kernel del pannello ricostruisce sempre lo zip dalla copia congelata del tag e ne verifica lo sha; rifiuta di
  sostituire panel.json finché i risultati del pannello precedente non sono stati scaricati (status.py attribuisce
  l'output del kernel al tag scritto in panel.json).
- Limiti noti del metodo: il pannello è piccolo (21–22 risolvibili), di un solo repository e con un solo run a
  temperatura 1.0 (differenze di 1–2 task sono rumore); il punteggio pubblico è un singolo run su ~58 task
  (± ~0,08). I task nascosti sono di repository privati diversi.
"""

SEC6_S6 = """### 6.1 S6 in dettaglio
**Diagnosi (verificata su codice e tracce).** In S1–S4 i tool con un solo argomento di testo non si rompono quasi
mai, quelli con due argomenti di codice sì (tabella sotto, calcolata da results/failure_audit.json). La causa è nel
formato di chiamata di Gemma 4 e nel parser "gemma4" di vLLM 0.19.1 (vllm/tool_parsers/gemma4_tool_parser.py,
letto nel sorgente): una chiamata ha la forma call:nome{{chiave:<|"|>valore<|"|>,...}}; il parser chiude una stringa
SOLO al token <|"|>; il modello emette le chiavi in ordine alfabetico (osservato nelle tracce: edit_file 133 volte
su 134 come filepath, new_string, old_string; write_file come content, filepath; run_skill_script come args,
file_path, skill_name; coerente con un template che ordina le proprietà, non verificato nel template). Quando il modello chiude il codice di new_string con un backtick
invece del token, tutto ciò che segue (",old_string:" e il vecchio testo) finisce dentro new_string e old_string
risulta mancante: errore "mandatory input parameters are not present: old_string", e il modello rimanda la stessa
chiamata (fino a 13 volte in un task). Se invece apre un valore senza il token, il parser lo legge come valore
"nudo" fino alla prima virgola e il resto del codice diventa nomi di chiavi spazzatura. run_command ha un solo
argomento: anche se chiuso male, non c'è nulla dopo da inghiottire. Sul timeout l'harness valuta comunque il
working tree (agent_runner: fallback git diff), quindi una modifica mai applicata è una perdita secca.

{tool_table}

Perdite per categoria (run di S1–S4 sommati; gli stessi 24 task ripetuti, quindi non indipendenti):

{loss_table}

**Intervento (una sola variabile: il canale con cui il codice arriva al file).**
1. agent.yaml: tool = run_command, read_file, get_status, submit_patch (+ skill). Tolti edit_file e write_file;
   tolto replace_lines.py. Il resto (sampling, thinking 1.024, budget 5 min/32 chiamate, localize, finalize) è
   identico a S5.
2. Nuovo script skills/swe/scripts/edit.py, invocato così (un solo argomento, il codice in un heredoc tra apici,
   quindi bash non tocca $, backtick e backslash):
       python3 /tmp/swe/edit.py percorso/modulo.py <<'EOF'
       <<<<<<< SEARCH
       righe attuali esatte
       =======
       righe nuove
       >>>>>>> REPLACE
       EOF
   Altre forme: "percorso A-B" + heredoc con le sole righe nuove sostituisce le righe A..B ("A-(A-1)" inserisce
   prima di A); un percorso che non esiste crea il file con il contenuto del heredoc.
3. Comportamento di edit.py (stdlib, compatibile Python ≥ 3.8):
   - percorso risolto con realpath dentro la root del repository (rifiuta ../ e symlink che escono); rifiuta test e
     file di configurazione dei test (stessa regex di finalize.py, test di parità);
   - più blocchi nello stesso comando, applicati in ordine su una copia in memoria: tutto o niente;
   - ricerca di SEARCH a livelli: esatta; ignorando spazi finali e righe vuote ai bordi; ignorando un rientro
     uniforme (la sostituzione viene re-indentata dello stesso scarto); righe copiate con i numeri che l'editor
     stesso stampa; deve essere UNICA (se compare più volte elenca le righe e non scrive);
   - più righe "=======" tra i marcatori (es. sottolineature RST nelle docstring): prova ogni divisione e sceglie,
     tra quelle con corrispondenza unica, il SEARCH più lungo;
   - se SEARCH non c'è: mostra la regione più simile con i numeri di riga (prefiltro fuzzy su 3 righe sonda, poi
     difflib) e suggerisce la forma per intervallo; se lo stesso blocco era già stato applicato da questo editor
     (registro in .git/swe_edit_journal, che git diff ignora) risponde "already applied" invece di errore;
   - controllo di compilazione: se il file compilava prima e non compilerebbe dopo, non scrive e mostra l'errore
     con le righe intorno (un file già rotto si può modificare, con avviso);
   - scrittura atomica (file temporaneo nella stessa cartella + os.replace), mantiene CRLF se tutto il file è
     CRLF, lascia byte per byte le righe non toccate dei file misti, mantiene newline finale e permessi;
   - robustezza alla chiamata rotta: ignora una riga finale "EOF" con backtick o virgolette rimasta nel testo,
     elimina il token <|"|> se trapelato; se il heredoc non è tra apici (bash avrebbe già espanso $, backtick e
     backslash) recupera il testo grezzo dalla riga di comando della shell in /proc (solo se nel comando c'è una
     sola invocazione dell'editor);
   - output sempre stampabile (stdout con errors=replace), ≤ 3.800 caratteri, exit 0 se applicato, 1 se non
     scritto (l'harness lo marca come errore e il modello vede il messaggio).
4. Installazione: localize.py (passo 1, sempre eseguito) copia edit.py in /tmp/swe/edit.py (fuori dal workspace,
   quindi mai nella patch) e stampa "EDITOR READY: python3 /tmp/swe/edit.py"; se /tmp non è scrivibile usa
   /workspace/.git/swe/edit.py e lo dice. finalize.py lo reinstalla quando la patch è vuota.
5. Prompt: passo 4 con l'esempio di heredoc; nuove regole di recupero (sezione 4).
6. Metriche: analysis/agent_traces.py e failure_audit.py contano come modifica anche run_command con edit.py
   (editor_calls, editor_not_applied, editor_unquoted); su S1–S4 i numeri restano identici (verificato).

**Verifiche fatte prima del pannello.**
- 31 test del bundle (tests/test_agent.py), anche con il Python 3.13 del venv dell'harness: blocchi in ordine,
  tutto-o-niente, livelli di ricerca, ambiguità, SEARCH vuoto, guardia di compilazione, idempotenza, "mai dire già
  applicato per una modifica non fatta", intervalli di righe, file nuovi, percorsi rifiutati, CRLF/misti/Unicode/
  permessi, "=======" dentro il codice, recupero del heredoc senza apici, un vero bash con heredoc tra apici,
  installazione tramite il wrapper ADK reale di run_skill_script, parità tra le copie, metriche sulle tracce.
- Compilazione ufficiale (adk_submission + google-adk dell'harness): tool compilati run_command, read_file,
  get_status, submit_patch, list_skills, load_skill, load_skill_resource, run_skill_script; caso peggiore 11,25 h.
- Kernel Linux (Python {ec_python}, {ec_bash}): {ec_passed}/{ec_total} casi superati, eseguiti con la stessa catena
  dell'harness (bash -c "timeout -k 5s N /bin/bash -c <comando>"): {ec_cases}. La prima versione ne aveva fallito
  uno: con un SEARCH sbagliato e la riga di REPLACE già presente altrove, l'editor diceva "già applicato";
  corretto con il registro dei blocchi applicati.

**Ipotesi e regola di decisione (scritte prima del pannello, RESUME.md).** Ipotesi: un solo valore di codice per
chiamata elimina la classe di errori (edit_file 73/208 malformate, run_command 0/807). READY se: risolti tra i
risolvibili ≥ migliore finora (S4 = 5, o S5 se più alto); task con un tentativo di modifica malformato ≤ 1;
editor_not_applied / editor_calls ≤ 0,35; NO_EDIT_TOOL = 0; nessun nuovo tipo di errore (editor mai installato,
heredoc senza apici che corrompono il codice, file temporanei nella patch, patch vuote + nessuna modifica oltre
3 + 2 di S4 di più di 2). Altrimenti BLOCKED.

**Stato.** S6 congelata (sha {s6_sha}), in coda: il suo pannello parte quando finisce quello di S5. Il prossimo
passo previsto (S7, non ancora costruito): dopo la prima modifica eseguire una volta il file di test correlato,
perché i fix sbagliati venivano controllati quasi solo con python -c scritti dal modello (14/17 controllati,
1/17 con pytest; nei risolti 6/17).
"""

SEC7 = """## 7. Il paper "Anchors Decide" — come è fatto
Domanda: dato solo il testo della issue, quanto spesso ogni segnale (identificatori, BM25, vicini negli embedding,
espansione del grafo delle chiamate, fusione RRF, e il modello Gemma 4) mette tra i primi k un simbolo che la
patch di riferimento modifica, con quale costo di lettura, e come combinarli.
Dati: 129 task pubblici (fastapi 67, rich 48, requests 13, httpx 1), grafi delle chiamate e embedding a 256
dimensioni forniti dalla gara; 114 task hanno almeno un simbolo "gold".
Etichette gold (locstudy/gold.py): per ogni hunk della patch di riferimento in un file sorgente (non test, docs,
esempi) si prende il nodo del grafo più specifico che contiene almeno il 50% delle righe rimosse (esclusi import,
commenti e righe < 4 caratteri); per aggiunte pure, un nodo che contiene ≥ 2 righe di contesto. Soglia fissata
prima dell'analisi. Audit: copertura completa 267/290 hunk; confronto con l'intestazione @@ di git; campioni
ispezionati.
Segnali (locstudy/signals.py, study.py): Identifiers e Identifiers+ (con traceback, import e chiamate nei blocchi
di codice) risolti come l'harness; BM25 sui nodi; vicini negli embedding e espansione del grafo a 1 o 2 passi a
partire dalle prime 3 ancore; RRF e RRF+ (k = 60); "lex" (post hoc) = la politica senza grafo usata dall'agente.
Metriche (locstudy/metrics.py): Recall@k (k = 1, 5, 10, 20, 50), MRR, varianti a livello di file, "reading budget"
= token (caratteri/4) di sorgente letti scorrendo la classifica fino al primo simbolo corretto, Hit@2k/8k/32k.
Statistica: intervalli percentili da 10.000 ricampionamenti bootstrap per task (seed 0); confronti appaiati con
McNemar esatto e correzione di Holm dentro ogni famiglia, più intervallo bootstrap della differenza; analisi di
sensibilità un parametro alla volta (k di RRF, numero di ancore, parametri BM25, severità delle etichette).
Esperimento con il modello (analysis/llm_v2.py, kernel Kaggle v2): Gemma 4 31B su 4×L4 (vLLM, TP 4,
max_model_len 16384, gpu_memory_utilization 0,80, max_num_seqs 16), temperatura 0, thinking disattivato, 114/114
task, 862 s totali. Tre usi: ipotesi di nomi di simboli (prompt P_HYP), ipotesi fuse con gli altri segnali, e
riordino dei primi 50 di BM25 mostrati come id + firma + docstring (prompt P_RERANK); più la "policy a due
modalità" (RRF+ se ci sono ancore, riordino altrimenti). Ipotesi H1–H3 e codice di analisi committati PRIMA di
scaricare i risultati (commit 6a28d29; prima delle riscritture della storia del 26/10 era 136a864, mappa in
results/commit_id_map.md); tutto il resto è marcato post hoc. Prompt esatti:
{prompts}
Garanzie di rigore: il testo è un template (paper/PAPER.template.md) con slot {{{{fonte:percorso|formato}}}} riempiti
dai file di risultati (nessun numero scritto a mano) e "claim" del tipo <!-- claim: a < 0.05 --> accanto alle
frasi: se i risultati contraddicono una frase la build fallisce; blocchi condizionali per sezioni che dipendono da
risultati opzionali; provenienza (hash dei dati, commit, versioni) in results/summary.json; test su dati
sintetici; CI su GitHub. Limiti dichiarati nel paper: 4 repository pubblici, etichette approssimate, un solo
prompt e un solo run per il modello, possibile memorizzazione dei repository pubblici da parte del modello.
Stato: {words} parole (la build fallisce oltre 3.000, contando tabelle e riferimenti), {claims} claim verificati;
sezione 4.10 riscritta il 26/10 dall'audit dei fallimenti (almeno metà delle perdite avviene dopo la
localizzazione; edit_file 73/208 malformate contro run_command 0/807); SweRank (ICLR 2026) aggiunto ai lavori
correlati; codice pubblico su GitHub e citato nel paper. Chiusura programmata il 5/11, scadenza 12/11 23:59 UTC.
"""

WHY = {
    "S1": "Prima versione: architettura della sezione 3, prompt con esempi di chiamata in formato codice.",
    "S2": ("Tracce S1: 53 chiamate malformate in 14/24 task (il modello copiava nei valori degli argomenti i backtick "
           "degli esempi del prompt, es. file_path \"scripts/localize.py`,skill_name:\"), 28 chiamate identiche "
           "ripetute, fino a 25 letture prima di modificare, 16 timeout. Modifiche: nessun backtick in tutto ciò che il "
           "modello legge (con test), chiamate descritte come campi con nome, limiti duri (≤ 3 letture prima della "
           "modifica, modifica entro la 6ª chiamata), nessuna chiamata dopo submit_patch, 32 chiamate massime."),
    "S3": ("Tracce S2: errori di argomenti scesi (14 → 5 task) ma 10–24 letture per task e prima modifica a 122 s di "
           "mediana. Modifiche: in modalità anchored localize mostra il codice del simbolo #1 (si modifica senza "
           "rileggerlo); finalize cancella /workspace/tmp (write_file('/tmp/x') finisce lì); il prompt lo spiega."),
    "S4": ("Analisi S3 dei 18 fallimenti: localizzazione non è il collo di bottiglia (file giusto nei primi 5 in 15/18); "
           "i turni di thinking al limite di 2.048 token (~60 s l'uno) occupano il 28–29% del tempo. Modifiche: "
           "thinking_budget 1024 e regola 'pensa poco, modifica l'opzione più plausibile e lascia decidere alla verifica'."),
    "S5": ("Analisi S4: 41/78 chiamate edit_file arrivate senza old_string (il modello chiudeva il primo valore con un "
           "backtick o una virgoletta e il resto della chiamata veniva inglobato), 7 task colpiti, chiamate identiche "
           "ripetute fino a 13 volte. Modifiche: script replace_lines.py (sostituzione per numero di riga, applicata solo "
           "se il file compila) e regola di recupero: dopo un errore di parametro mancante o due 'not found' non "
           "rimandare edit_file per quella modifica, usare il fallback."),
    "S6": ("Audit dei fallimenti S1–S4 e lettura del parser di vLLM: il codice arriva male al file quando una chiamata "
           "ha due argomenti di codice (le chiavi escono in ordine alfabetico e un backtick al posto del token di "
           "chiusura inghiotte quelle successive). Modifiche: edit_file, write_file e replace_lines tolti; editor "
           "edit.py chiamato con run_command e un heredoc tra apici (un solo argomento). Dettagli completi in 6.1."),
}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def bundle_files(tag: str) -> dict[str, str]:
    b = CAND / tag / "bundle"
    return {p.relative_to(b).as_posix(): read(p) for p in sorted(b.rglob("*")) if p.is_file()}


def fence(text: str, lang: str = "") -> str:
    ticks = "````" if "```" in text else "```"
    return f"{ticks}{lang}\n{text.rstrip()}\n{ticks}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--focus", default=None, help="only this tag: its detailed section, diff vs the previous tag, its files")
    a = ap.parse_args()
    a.out = a.out or ROOT.parent / (f"TECH_{a.focus}_{dt.date.today().isoformat()}.md" if a.focus
                                    else f"TECH_DEEP_DIVE_{dt.date.today().isoformat()}.md")
    tags = sorted((p.name for p in CAND.iterdir() if (p / "MANIFEST.json").exists()), key=lambda t: int(t[1:]))
    sha = {t: json.loads(read(CAND / t / "MANIFEST.json"))["zip_sha256"][:12] for t in tags}
    panels = {p.stem: json.loads(read(p)) for p in (ROOT / "results" / "agent_runs").glob("*.json")}
    lb = {r["experiment_id"]: r for r in csv.DictReader((ROOT / "runs.csv").open(encoding="utf-8"))}
    panel = json.loads(read(ROOT / "kernels" / "agent_eval" / "panel.json"))["panel"]
    src = read(ROOT / "analysis" / "llm_v2.py")
    prompts = "\n".join(m.group(0) for m in re.finditer(r"^(SYSTEM|P_HYP|P_RERANK) = .*?(?=^\S)", src, re.M | re.S))
    out = [INTRO.format(date=dt.date.today().isoformat(), first=tags[0], last=tags[-1], tags=", ".join(tags)),
           SEC1, SEC2, SEC3, SEC4, SEC5.format(panel=", ".join(panel))]

    out.append("## 6. Versione per versione\n")
    out.append("| Versione | sha256 (12) | Risolti/risolvibili (pannello) | Timeout | Patch vuote | Nessuna modifica | "
               "Task con chiamate malformate | Chiamate malformate | Prima modifica (mediana s) | Classifica pubblica |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for t in tags:
        s = panels.get(t, {}).get("summary")
        score = lb.get(t, {}).get("public_score") or ("non inviata" if t in panels else "in prova")
        row = (f"| {t} | {sha[t]} | {s['resolved_on_solvable']}/{s['gold_solvable']} | {s['timeouts']} | {s['empty_patch']} | "
               f"{s['no_edit']} | {s['tasks_with_arg_errors']} | {s['totals'].get('arg_errors', 0)} | {s['first_edit_s_median']} | {score} |"
               if s else f"| {t} | {sha[t]} | prova in corso | – | – | – | – | – | – | {score} |")
        out.append(row)
    out.append("\nDecisioni: S1 inviata (0,15). S2 non inviata (pari a S1 sul pannello, superata da S3). S3 inviata (0,12, "
               "differenza con S1 di ~2 task, nel rumore). S4 migliore sul pannello (5/22) ma BLOCCATA per la ricomparsa "
               "delle chiamate malformate. S5 e S6: stato e regole nella coda di RESUME.md (sotto lo stato al momento "
               "della generazione).\n")
    queue = [l for l in read(ROOT / "RESUME.md").splitlines() if re.match(r"\| S\d+ \| ", l)]
    queue_md = ("## 2. Coda in RESUME.md al momento della generazione\n\n| Tag | Stato | Modifica | Ipotesi |\n|---|---|---|---|\n"
                + "\n".join(queue) + "\n")
    out.append(queue_md.replace("## 2. Coda", "Coda"))
    for t in tags:
        out.append(f"### {t}\n{WHY.get(t, '')}\n")
    audit = json.loads(read(ROOT / "results" / "failure_audit.json"))["aggregate"]
    tool_table = "| Tool | Chiamate | Malformate | Tasso |\n|---|---|---|---|\n" + "\n".join(
        f"| {k} | {v['calls']} | {v['malformed']} | {100 * v['rate']:.1f}% |" for k, v in audit["tools"].items())
    loss_table = (f"Run risolvibili {audit['solvable_runs']} su {audit['task_runs']}; risolti {audit['resolved_runs']}; "
                  f"file giusto al rango 1 di localize in {audit['rank1_runs']} ({100 * audit['rank1_rate']:.1f}%).\n\n"
                  "| Categoria (run non risolti) | Run |\n|---|---|\n"
                  + "\n".join(f"| {k} | {v} |" for k, v in audit["unresolved"].items()))
    ec = json.loads(read(ROOT / "results" / "editor_check" / "editor_check.json"))
    s6 = "S6" if "S6" in sha else tags[-1]
    out.append(SEC6_S6.format(tool_table=tool_table, loss_table=loss_table, ec_python=ec["python"], ec_bash=ec["bash"],
                              ec_passed=ec["passed"], ec_total=ec["total"], s6_sha=sha[s6],
                              ec_cases="; ".join(r["case"] for r in ec["results"])))

    if a.focus:
        prev = tags[tags.index(a.focus) - 1]
        fa, fb = bundle_files(prev), bundle_files(a.focus)
        changed = [n for n in sorted(fb) if fa.get(n) != fb[n]]
        focus = [f"# {a.focus} — come è fatto (generato il {dt.date.today().isoformat()} da tools/tech_report.py --focus {a.focus})",
                 "Codice: https://github.com/emamira02/gemma4-swe-agent (cartella candidates/" + a.focus + "/bundle = "
                 "esattamente ciò che viene valutato e inviato). Contesto completo in TECH_DEEP_DIVE_<data>.md e "
                 "HANDOFF_2026-10-26.md.\n", out[-1].replace("### 6.1", "## 1."), queue_md,
                 f"## 3. Differenze esatte {prev} → {a.focus} (unified diff)\n"]
        removed = [n for n in sorted(fa) if n not in fb]
        for name in [n for n in changed if n in fa] + removed:  # new files appear in full in section 4 instead
            d = "".join(difflib.unified_diff(fa.get(name, "").splitlines(True), fb.get(name, "").splitlines(True),
                                             f"{prev}/{name}", f"{a.focus}/{name}", n=2))
            focus.append(fence(d, "diff") + "\n")
        full = [n for n in changed if n not in fa or len(fb[n]) < 12000]  # big modified files: the diff is enough
        focus.append(f"## 4. Testo completo dei file nuovi o brevi di {a.focus} ({', '.join(full)})\n")
        for name in full:
            focus.append(f"### {name}\n{fence(fb[name], LANG.get(Path(name).suffix, ''))}\n")
        text = "\n".join(focus)
        a.out.write_text(text, encoding="utf-8")
        print(f"wrote {a.out} ({len(text):,} chars, {len(text.split()):,} words)")
        return 0

    paper_md = read(ROOT / "paper" / "PAPER.md")
    tpl = read(ROOT / "paper" / "PAPER.template.md")
    words = len(re.sub(r"<!--.*?-->", " ", paper_md, flags=re.S).split())
    out.append(SEC7.format(prompts=fence(prompts, "python"), words=f"{words:,}".replace(",", "."),
                           claims=len(re.findall(r"<!-- claim:", tpl))))

    last = tags[-1]
    out.append(f"## 8. Appendice A — bundle completo di {last} (sha256 {sha[last]}), testo esatto\n")
    for name, text in bundle_files(last).items():
        out.append(f"### {name}\n{fence(text, LANG.get(Path(name).suffix, ''))}\n")

    out.append("## 9. Appendice B — differenze esatte tra versioni consecutive (unified diff)\n")
    for prev, cur in zip(tags, tags[1:]):
        fa, fb = bundle_files(prev), bundle_files(cur)
        out.append(f"### {prev} → {cur}\n")
        for name in sorted(set(fa) | set(fb)):
            d = "".join(difflib.unified_diff(fa.get(name, "").splitlines(True), fb.get(name, "").splitlines(True),
                                             f"{prev}/{name}", f"{cur}/{name}", n=2))
            if d:
                out.append(fence(d, "diff") + "\n")

    out.append("## 10. Appendice C — paper completo (paper/PAPER.md) e tabelle generate\n")
    for f in ("PAPER.md", "RESULTS.md", "RESULTS_LLM.md", "RESULTS_AGENT.md"):
        out.append(f"### paper/{f}\n" + read(ROOT / "paper" / f).strip() + "\n")
    text = "\n".join(out)
    a.out.write_text(text, encoding="utf-8")
    print(f"wrote {a.out} ({len(text):,} chars, {len(text.split()):,} words)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
