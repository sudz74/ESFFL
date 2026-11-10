"""Phase 1 coverage report: what does the Yahoo API actually return, per season?

Run:  PYTHONPATH=src python -m esffl.yahoo.coverage [--discover-only] [--refresh]

1. Resolves NFL game_keys per season.
2. Walks the league chain from the seed via renew/renewed.
3. Lists every league the login belongs to per season; flags chain members,
   same-name siblings (parallel/overlap-year candidates) and others.
4. Deep-pulls chain + sibling + include_keys leagues (settings, standings, teams,
   weekly scoreboards) into data/raw/yahoo/ and writes reports/yahoo_coverage.{csv,md}.
"""
import argparse
import csv
from pathlib import Path

import yaml

from . import client
from .client import YahooError, find_all, first


def key_parts(key):
    gk, lid = key.split(".l.")
    return gk, lid


def to_int(x, default=None):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def game_keys(start, end, refresh):
    seasons = ",".join(str(s) for s in range(start, end + 1))
    data = client.fetch(f"games;game_codes=nfl;seasons={seasons}", "_discovery", "games", refresh)
    out = {}
    for g in find_all(data, "game"):
        s = to_int(g.get("season"))
        if g.get("code") == "nfl" and s and g.get("game_key"):
            out[s] = str(g["game_key"])
    return out


def user_leagues(season, gk, refresh):
    try:
        data = client.fetch(f"users;use_login=1/games;game_keys={gk}/leagues",
                            "_discovery", f"user_leagues_{season}", refresh)
    except YahooError as e:
        return [], str(e)
    return find_all(data, "league"), None


def walk_chain(seed_key, refresh):
    """Follow renew (back) and renewed (forward) from the seed. Returns ({key: meta}, [gap notes])."""
    chain, gaps = {}, []

    def meta(key):
        d = client.fetch(f"league/{key}", "_chain", key.replace(".", "_"), refresh)
        return first(d, "league")

    def walk(key, field):
        seen = set()
        while key and key not in seen:
            seen.add(key)
            try:
                m = chain.get(key) or meta(key)
            except YahooError as e:
                gaps.append(f"{key} ({field}): {e}")
                return
            chain[key] = m
            nxt = m.get(field)
            key = nxt.replace("_", ".l.") if nxt else None

    walk(seed_key, "renew")
    m = chain.get(seed_key, {})
    fwd = m.get("renewed")
    walk(fwd.replace("_", ".l.") if fwd else None, "renewed")
    return chain, gaps


def pull_league(season, key, refresh):
    """Deep-pull one league. Returns dict of parsed pieces + error list."""
    _, lid = key_parts(key)
    scope = f"{season}/{lid}"
    res = {"errors": [], "boards": {}}

    def f(path, name):
        try:
            return client.fetch(path, scope, name, refresh)
        except YahooError as e:
            res["errors"].append(f"{name}: {e}")
            return None

    res["league"] = first(f(f"league/{key}", "league") or {}, "league")
    res["settings"] = first(f(f"league/{key}/settings", "settings") or {}, "settings")
    res["standings"] = f(f"league/{key}/standings", "standings") or {}
    res["private_standings"] = client.load_private(scope, "standings") or {}
    f(f"league/{key}/teams", "teams")
    lg = res["league"]
    start = to_int(lg.get("start_week"), 1)
    end = to_int(lg.get("end_week"), 17)
    res["weeks"] = (start, end)
    for w in range(start, end + 1):
        sb = f(f"league/{key}/scoreboard;week={w}", f"scoreboard_w{w:02d}")
        if sb:
            res["boards"][w] = sb
    return res


def identities(season, key, pulled):
    """Local-only lookup rows (email/guid/nickname per team) for manual owner identification."""
    _, lid = key_parts(key)
    rows = []
    for t in find_all(pulled.get("private_standings") or {}, "team"):
        for m in find_all(t, "manager") or [{}]:
            rows.append({
                "season": season, "league_id": lid, "team_key": t.get("team_key", ""),
                "team_id": t.get("team_id", ""), "team_name": t.get("name", ""),
                "manager_id": m.get("manager_id", ""), "nickname": m.get("nickname", ""),
                "email": m.get("email", ""), "guid": m.get("guid", ""),
                "is_commissioner": m.get("is_commissioner", ""),
                "is_current_login": m.get("is_current_login", ""),
                "guid_h": client.scrub({"guid": m.get("guid")}).get("guid_h") or ""})
    return rows


def summarize(season, key, in_chain, pulled):
    lg, st = pulled["league"], pulled["settings"]
    teams = find_all(pulled["standings"], "team")
    with_record = 0
    guid_vis = 0
    for t in teams:
        ot = (t.get("team_standings") or {}).get("outcome_totals") or {}
        if ot.get("wins") not in (None, ""):
            with_record += 1
        if any(m.get("guid_h") for m in find_all(t, "manager")):
            guid_vis += 1
    email_vis = sum(1 for t in find_all(pulled.get("private_standings") or {}, "team")
                    if any(m.get("email") for m in find_all(t, "manager")))
    scored_weeks = matchups = playoff = consol = 0
    for w, sb in pulled["boards"].items():
        wk_scored = 0
        for m in find_all(sb, "matchup"):
            ts = find_all(m, "team")
            pts = [(t.get("team_points") or {}).get("total") for t in ts]
            if len(ts) == 2 and all(p not in (None, "") for p in pts):
                wk_scored += 1
                matchups += 1
                playoff += m.get("is_playoffs") == "1"
                consol += m.get("is_consolation") == "1"
        scored_weeks += wk_scored > 0
    start, end = pulled["weeks"]
    expected = end - start + 1
    n_teams = to_int(lg.get("num_teams"), 0)
    if not teams:
        status = "MISSING"
    elif pulled["errors"] or with_record < len(teams) or scored_weeks < expected or len(teams) != n_teams:
        status = "PARTIAL"
    else:
        status = "OK"
    return {
        "season": season, "league_key": key, "name": lg.get("name", ""), "in_chain": in_chain,
        "num_teams_meta": n_teams, "teams_in_standings": len(teams), "rows_with_record": with_record,
        "managers_with_guid": guid_vis, "managers_with_email": email_vis, "weeks_expected": expected, "weeks_with_scores": scored_weeks,
        "matchups_scored": matchups, "playoff_matchups": playoff, "consolation_matchups": consol,
        "playoff_start_week": st.get("playoff_start_week", ""), "num_playoff_teams": st.get("num_playoff_teams", ""),
        "is_finished": lg.get("is_finished", ""), "status": status, "errors": " | ".join(pulled["errors"])[:300],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/leagues.yml")
    ap.add_argument("--refresh", action="store_true", help="re-fetch even if raw snapshot exists")
    ap.add_argument("--discover-only", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())["yahoo"]
    start, end = cfg["seasons"]
    gks = game_keys(start, end, args.refresh)
    print(f"game_keys resolved for {len(gks)} of {end - start + 1} seasons")
    missing = [s for s in range(start, end + 1) if s not in gks]
    if missing:
        print("  no game_key for:", missing)

    seed = cfg["seed"]
    seed_gk = gks.get(seed["season"])
    if not seed_gk:
        raise SystemExit(f"Could not resolve game_key for seed season {seed['season']}")
    seed_key = f"{seed_gk}.l.{seed['league_id']}"
    chain, gaps = walk_chain(seed_key, args.refresh)
    chain_names = {m.get("name", "").strip().lower() for m in chain.values()}
    print(f"chain from {seed_key}: {len(chain)} leagues; gaps: {gaps or 'none'}")

    targets = {}  # key -> (season, tag)
    other = []
    for s, gk in sorted(gks.items()):
        leagues, err = user_leagues(s, gk, args.refresh)
        if err:
            print(f"  {s}: user-leagues lookup failed: {err}")
        for lg in leagues:
            key = lg.get("league_key")
            name = lg.get("name", "")
            if key in chain:
                tag = "chain"
            elif name.strip().lower() in chain_names:
                tag = "sibling"
            elif key in (cfg.get("include_keys") or []):
                tag = "include"
            else:
                other.append((s, key, name, lg.get("num_teams")))
                continue
            targets[key] = (s, tag)
    for key, m in chain.items():
        s = to_int(m.get("season"))
        if s and start <= s <= end + 1:
            targets.setdefault(key, (s, "chain"))
    for key in cfg.get("include_keys") or []:
        if key not in targets:
            gk, _ = key_parts(key)
            s = next((x for x, g in gks.items() if g == gk), None)
            targets[key] = (s, "include")

    print(f"\n{len(targets)} leagues to pull; {len(other)} other leagues on this login skipped:")
    for s, key, name, n in other:
        print(f"  {s} {key} '{name}' ({n} teams)")
    if args.discover_only:
        return

    rows, ident = [], []
    for key, (s, tag) in sorted(targets.items(), key=lambda kv: (kv[1][0] or 0, kv[0])):
        print(f"pulling {s} {key} [{tag}] ...")
        pulled = pull_league(s, key, args.refresh)
        row = summarize(s, key, tag, pulled)
        rows.append(row)
        ident.extend(identities(s, key, pulled))
        print(f"   -> {row['status']}: {row['teams_in_standings']} teams, {row['weeks_with_scores']}/{row['weeks_expected']} weeks")

    if ident:
        Path("data/private").mkdir(parents=True, exist_ok=True)
        with open("data/private/yahoo_identities.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(ident[0]))
            w.writeheader()
            w.writerows(ident)
        print("Wrote data/private/yahoo_identities.csv (local only, gitignored)")

    Path("reports").mkdir(exist_ok=True)
    cols = list(rows[0]) if rows else []
    with open("reports/yahoo_coverage.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open("reports/yahoo_coverage.md", "w") as fh:
        short = ["season", "league_key", "name", "in_chain", "teams_in_standings", "rows_with_record",
                 "managers_with_guid", "managers_with_email", "weeks_with_scores", "weeks_expected", "matchups_scored", "status"]
        fh.write("| " + " | ".join(short) + " |\n|" + "---|" * len(short) + "\n")
        for r in rows:
            fh.write("| " + " | ".join(str(r[c]) for c in short) + " |\n")
        if gaps:
            fh.write("\nChain gaps:\n" + "\n".join(f"- {g}" for g in gaps) + "\n")
        if other:
            fh.write("\nOther leagues on this login (not pulled):\n" +
                     "\n".join(f"- {s} {k} {n}" for s, k, n, _ in other) + "\n")
    print("\nWrote reports/yahoo_coverage.csv and .md")


if __name__ == "__main__":
    main()
