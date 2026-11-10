"""Offline tests with synthetic payloads shaped like Yahoo's JSON. Run: PYTHONPATH=src python tests/test_yahoo_parse.py"""
from esffl.yahoo import client
from esffl.yahoo.coverage import summarize

STANDINGS = {"fantasy_content": {"league": [
    {"league_key": "338.l.46149", "name": "ESFFL", "num_teams": 2, "season": "2021"},
    {"standings": [{"teams": {"0": {"team": [
        [{"team_key": "338.l.46149.t.1"}, {"name": "A"}, [],
         {"managers": [{"manager": {"manager_id": "1", "nickname": "x", "guid": "ABCDEF", "email": "a@b.c"}}]}],
        {"team_standings": {"rank": 1, "outcome_totals": {"wins": "10", "losses": "3", "ties": "0"}}}]},
        "1": {"team": [
        [{"team_key": "338.l.46149.t.2"}, {"name": "B"},
         {"managers": [{"manager": {"manager_id": "2", "nickname": "y", "guid": "--"}}]}],
        {"team_standings": {"rank": 2, "outcome_totals": {"wins": "3", "losses": "10", "ties": "0"}}}]},
        "count": 2}}]}]}}


def board(week, a, b, playoff="0"):
    return {"fantasy_content": {"league": [{"league_key": "338.l.46149"}, {"scoreboard": {"0": {"matchups": {"0": {"matchup": {
        "week": str(week), "is_playoffs": playoff, "is_consolation": "0",
        "0": {"teams": {"0": {"team": [[{"team_key": "t1"}], {"team_points": {"total": a}}]},
                        "1": {"team": [[{"team_key": "t2"}], {"team_points": {"total": b}}]}, "count": 2}}}},
        "count": 1}}}}]}}


def test_scrub_and_flatten():
    s = client.scrub(STANDINGS)
    txt = str(s)
    assert "a@b.c" not in txt and "ABCDEF" not in txt and "guid_h" in txt
    flat = client.flatten(s)
    teams = client.find_all(flat, "team")
    assert len(teams) == 2
    assert teams[0]["name"] == "A" and teams[0]["team_standings"]["outcome_totals"]["wins"] == "10"
    mgrs = [m for t in teams for m in client.find_all(t, "manager")]
    assert mgrs[0]["guid_h"] and mgrs[1]["guid_h"] is None  # hidden guid stays None, not a shared hash


def test_summarize():
    flat = client.flatten(client.scrub(STANDINGS))
    boards = {1: client.flatten(board(1, "100.5", "90.2")), 2: client.flatten(board(2, "", "", "1"))}
    pulled = {"errors": [], "boards": boards, "weeks": (1, 2),
              "league": {"num_teams": "2", "name": "ESFFL", "is_finished": "1"},
              "settings": {"playoff_start_week": "14"}, "standings": flat}
    r = summarize(2021, "338.l.46149", "chain", pulled)
    assert r["teams_in_standings"] == 2 and r["rows_with_record"] == 2
    assert r["managers_with_guid"] == 1
    assert r["weeks_with_scores"] == 1 and r["status"] == "PARTIAL"  # week 2 unscored


if __name__ == "__main__":
    test_scrub_and_flatten()
    test_summarize()
    print("ok")
