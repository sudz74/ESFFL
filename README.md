# ESFFL
Hub for ESFFL History and Tools

## Setup (local)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET
export PYTHONPATH=src
```

## Phase 1: Yahoo auth + coverage report
```bash
python -m esffl.yahoo.auth                       # one-time OAuth, writes .yahoo_token.json (gitignored)
python -m esffl.yahoo.coverage --discover-only   # game keys, chain, all leagues on the login
python -m esffl.yahoo.coverage                   # deep pull + reports/yahoo_coverage.{csv,md}
python tests/test_yahoo_parse.py                 # offline parser tests
```
Raw responses land in `data/raw/yahoo/{season}/{league_id}/` with emails removed and manager
guids replaced by a one-way hash (`guid_h`). Existing snapshots are never overwritten unless `--refresh`.
