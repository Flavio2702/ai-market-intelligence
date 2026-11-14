# AI Market Intelligence

[![Test](https://github.com/Flavio2702/ai-market-intelligence/actions/workflows/tests.yml/badge.svg)](https://github.com/Flavio2702/ai-market-intelligence/actions/workflows/tests.yml)

**Dai contenuti dei concorrenti a un confronto strutturato, con fonti e limiti dei dati visibili.**

MVP locale in Python e PostgreSQL per raccogliere pagine web selezionate, estrarre informazioni con AI e produrre report di competitive content intelligence. Progetto di portfolio in sviluppo: non è un servizio pronto per la produzione.

## Il problema

Confrontare manualmente siti concorrenti rende difficile distinguere messaggi ricorrenti, prove, prezzi e aree poco coperte. Questa pipeline conserva i dati raccolti, struttura le osservazioni e separa gli indicatori utilizzabili dai segnali deboli.

Rispetto a [Senti](https://github.com/Flavio2702/senti-brand-signals), che esplora la percezione pubblica attraverso recensioni e altre fonti esterne, questo progetto analizza soprattutto **i contenuti che le aziende pubblicano sui propri siti**.

## Esempio senza installazione

Leggi il [report dimostrativo](examples/report-demo.md): contiene soltanto dati inventati, non risultati di un crawl reale. Anche i CSV inclusi usano domini `.example`, non navigabili: sostituirli prima di un utilizzo live.

## Come funziona

```text
CSV → Crawl4AI → PostgreSQL → estrazione OpenAI/Pydantic
                           → indicatori e temi → report Markdown
                           → viste SQL → Superset esterno (opzionale)
```

- Raccolta delle sole URL configurate, con registrazione degli errori e deduplicazione.
- Estrazione strutturata di messaggi, caratteristiche, prezzi e prove.
- Controlli sulla validità delle pagine e sulla copertura del campione.
- Tassonomia configurabile per i temi strategici; BERTopic per analisi esplorativa.
- Report generati da SQL, con sintesi AI opzionale e distinzione fra dati disponibili e non valutabili.

La configurazione di esempio conserva un dominio applicativo audio: è una tassonomia dimostrativa, da adattare al proprio settore.

## Avvio rapido

Requisiti: Python 3.12 (versione usata per i test), PostgreSQL dedicato, chiave OpenAI per l'estrazione live.

```sh
git clone https://github.com/Flavio2702/ai-market-intelligence.git
cd ai-market-intelligence
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Copia `.env.example` in `.env`, configura credenziali locali e crea il database indicato in `DATABASE_URL`. Sostituisci i CSV dimostrativi in `data/` con URL pubbliche appropriate e adatta `config/content_topics.yml`. Il campo `is_owned_domain` identifica facoltativamente il sito da confrontare.

**Attenzione: il caricamento CSV sostituisce il dataset configurato**, inclusi dati raccolti e analisi precedenti. Usa un database dedicato e conserva separatamente ciò che vuoi mantenere.

```sh
python scripts/run_pipeline.py --crawl-limit 15 --extract-limit 15
```

I report vengono scritti in `outputs/reports/`. Le chiamate OpenAI possono avere un costo. Il codice e i test non richiedono chiavi incorporate nel repository.

## Verifiche e limiti

```sh
pip install -r requirements-test.txt
python -m pytest -q
```

I test automatici simulano database e servizi esterni. Non attestano il funzionamento end-to-end con PostgreSQL, siti live, OpenAI o Superset, né la qualità delle conclusioni AI. Nessuna chiamata a pagamento viene eseguita dalla CI.

Il progetto dimostra pipeline dati, modellazione SQL, estrazione strutturata, test e gestione dell'incertezza. Non calcola quote di mercato reali: volume di testo raccolto e sentiment del corpus sono diagnostiche. Campioni piccoli e dati mancanti limitano il confronto. Le estrazioni AI richiedono revisione umana. Non sono presenti frontend o dashboard incorporati; Superset va configurato separatamente.

## Documentazione

- [Guida operativa completa](docs/OPERATIONS.md) — comandi, affidabilità, comportamento del reset e troubleshooting (in inglese).
- [Collegamento a Superset](docs/superset_setup.md) — configurazione esterna e viste disponibili (in inglese).
- [Dipendenze e attribuzioni](THIRD_PARTY_NOTICES.md).

Non inserire credenziali, dump, dati riservati o report di clienti nei commit. La pubblicazione include esclusivamente esempi sintetici e una nuova cronologia, senza i dati del progetto locale.

## Licenza

Copyright 2026 Flavio2702. Contributi originali sotto [Apache License 2.0](LICENSE). Le dipendenze mantengono le proprie licenze; vedi [NOTICE](NOTICE).
