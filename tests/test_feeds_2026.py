"""Iowa, South Carolina and Texas 2026 results feeds, offline, on saved official files.

    uv run pytest

Samples in data/reference/enr_samples/ (fetched 2026-11-02):
- IA 127077, SC 127300: the 2026 general placeholders (zero votes);
- IA 122322, SC 122436: the 2024 general, final;
- TX Dallas 127396, Tarrant 127297, Denton 127398, Fort Bend 127480, Williamson 127488,
  El Paso 127348: 2026 county placeholders; Dallas 122494, Tarrant 122489, Denton 122426,
  Fort Bend 122596, El Paso 122595, Travis 122432: 2024 county files. The Dallas and
  Tarrant files are trimmed to the tracked contests (their full files are 0.7-1.9 MB).
`scripts/feeds_2026_check.py` runs the same adapters against the live hosts.
"""

from __future__ import annotations

import json
import zipfile

import pandas as pd
import pytest

from midterms.live import feeds as F
from midterms.live import feeds_tx as T
from midterms.live.baselines import county_baseline

SAMPLES = F.ROOT / "data" / "reference" / "enr_samples"


def xml(path: str) -> bytes:
    return zipfile.ZipFile(SAMPLES / path).read("detail.xml")


# ---- election ids --------------------------------------------------------------------

def test_2026_ids_are_set():
    assert F.IA_EID_2026 == "127077"
    assert F.SC_EID_2026 == "127300"


def test_feed_ids_override(tmp_path, monkeypatch):
    f = tmp_path / "feed_ids.json"
    monkeypatch.setattr(F, "FEED_IDS_FILE", tmp_path / "missing.json")
    assert F.feed_id("IA", "127077") == "127077"           # no file: the default
    monkeypatch.setattr(F, "FEED_IDS_FILE", f)
    f.write_text(json.dumps({"IA": 130000, "SC": ""}))
    assert F.feed_id("IA", "127077") == "130000"           # the file wins
    assert F.feed_id("SC", "127300") == "127300"           # empty entry: the default
    with pytest.raises(RuntimeError, match="not set"):
        F.feed_id("SC", None)
    f.write_text("{not json")
    with pytest.raises(RuntimeError, match="unreadable"):
        F.feed_id("IA", "127077")


def test_override_files_live_in_the_repo():
    # the error messages name the file relative to the repo, so it must live under ROOT
    assert F.FEED_IDS_FILE.is_relative_to(F.ROOT)
    assert T.SOURCES_FILE.is_relative_to(F.ROOT)


def test_adapters_use_the_2026_ids(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(F, "FEED_IDS_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(F, "clarity", lambda st, eid, expect_date=None: calls.append((st, eid, expect_date)) or F._frame([]))
    F.ADAPTERS["IA"]()
    F.ADAPTERS["SC"]()
    assert calls == [("IA", "127077", "11/3/2026"), ("SC", "127300", "11/3/2026")]


# ---- Clarity statewide (IA, SC) -------------------------------------------------------

@pytest.mark.parametrize("state,path,races,counties", [
    ("IA", "IA/detailxml_127077_2026-11-02.zip", {"SEN-IA", "GOV-IA", "IA-01", "IA-02", "IA-03", "IA-04"}, 99),
    ("SC", "SC/detailxml_127300_2026-10-30.zip",
     {"SEN-SC", "GOV-SC"} | {f"SC-0{i}" for i in range(1, 8)}, 46),
])
def test_clarity_2026_placeholder(state, path, races, counties):
    body = xml(path)
    F.clarity_check_date(state, "x", body, "11/3/2026")      # doesn't raise
    df = F.clarity_xml(state, body)
    assert set(df["race"]) == races
    assert df["fips"].notna().all() and df["fips"].nunique() == counties
    assert df["votes"].sum() == 0 and not df["complete"].any()
    assert "other" not in set(df["vote_type"])               # every vote-type label is mapped


@pytest.mark.parametrize("state,path", [("IA", "IA/detailxml_122322_2024.zip"), ("SC", "SC/detailxml_122436_2024.zip")])
def test_clarity_date_check_refuses_another_election(state, path):
    with pytest.raises(RuntimeError, match="not 11/3/2026"):
        F.clarity_check_date(state, "x", xml(path), "11/3/2026")


@pytest.mark.parametrize("state,path", [("IA", "IA/detailxml_122322_2024.zip"), ("SC", "SC/detailxml_122436_2024.zip")])
def test_clarity_2024_matches_baseline(state, path):
    df = F.clarity_xml(state, xml(path))
    p = df[df["race"] == f"PRES-{state}"]
    got = p[p["party"].isin(["D", "R"])].pivot_table(index="fips", columns="party", values="votes", aggfunc="sum")
    b = county_baseline(state).set_index("fips").loc[got.index]
    assert len(got) == len(county_baseline(state))
    assert (got["D"] == b["pres2024_dem"]).all() and (got["R"] == b["pres2024_gop"]).all()
    assert p.groupby("fips")["complete"].all().all()
    assert "other" not in set(df["vote_type"])


# ---- Texas counties --------------------------------------------------------------------

@pytest.mark.parametrize("county,path,fips,house,types", [
    ("Dallas", "TX/detailxml_Dallas_127396.zip", "48113", {"TX-05", "TX-06", "TX-24", "TX-30", "TX-32", "TX-33"},
     {"early", "election_day", "mail"}),
    ("Tarrant", "TX/detailxml_Tarrant_127297.zip", "48439", {"TX-06", "TX-12", "TX-24", "TX-25", "TX-30"},
     {"early", "election_day", "mail"}),
    ("Fort Bend", "TX/detailxml_Fort_Bend_127480.zip", "48157", {"TX-07", "TX-14", "TX-18", "TX-22"},
     {"early", "election_day", "mail"}),
    ("Denton", "TX/detailxml_Denton_127398.zip", "48121", {"TX-04", "TX-13", "TX-26"}, {"early", "election_day", "mail"}),
    ("El Paso", "TX/detailxml_El_Paso_127348.zip", "48141", {"TX-16", "TX-23"}, {"early", "election_day", "mail"}),
    # no 2024 file, so no measured vote-type leans: folded into one total per candidate
    ("Williamson", "TX/detailxml_Williamson_127488.zip", "48491", {"TX-11", "TX-17", "TX-31"}, {"total"}),
])
def test_tx_2026_placeholder(county, path, fips, house, types):
    df = T.county_xml(county, xml(path), expect_date="11/3/2026")
    assert set(df["race"]) == {"SEN-TX", "GOV-TX"} | house    # no city "Representative" races
    assert set(df["fips"]) == {fips}
    assert df["votes"].sum() == 0
    assert set(df["vote_type"]) == types
    sen = df[df["race"] == "SEN-TX"].groupby("party")["candidate"].first()
    assert sen["D"].title() == "James Talarico" and sen["R"].title() == "Ken Paxton"


def test_tx_date_check_refuses_another_election():
    with pytest.raises(RuntimeError, match="not 11/3/2026"):
        T.county_xml("Denton", xml("TX/detailxml_Denton_122426.zip"), expect_date="11/3/2026")


@pytest.mark.parametrize("county,path,tol", [
    ("Denton", "TX/detailxml_Denton_122426.zip", 0),
    ("El Paso", "TX/detailxml_El_Paso_122595.zip", 0),
    ("Travis", "TX/detailxml_Travis_122432.zip", 20),        # canvass vs the compiled baseline: 13 D, 6 R
    ("Tarrant", "TX/detailxml_Tarrant_122489.zip", 0),
    ("Fort Bend", "TX/detailxml_Fort_Bend_122596.zip", 0),
    ("Dallas", "TX/detailxml_Dallas_122494.zip", 110),       # Dallas's 11/15 file, before the canvass: 91 D, 101 R
])
def test_tx_2024_matches_baseline(county, path, tol):
    df = T.county_xml(county, xml(path), T.CANDIDATES_2024, expect_date="11/5/2024")
    p = df[df["race"] == "PRES-TX"].groupby("party")["votes"].sum()
    b = county_baseline("TX").set_index("fips").loc[df["fips"].iloc[0]]
    assert abs(p["D"] - b["pres2024_dem"]) <= tol and abs(p["R"] - b["pres2024_gop"]) <= tol


def test_tx_travis_party_prefix():
    df = T.county_xml("Travis", xml("TX/detailxml_Travis_122432.zip"), {}, expect_date=None)
    sen = df[df["race"] == "SEN-TX"].groupby("party")["candidate"].first()
    assert sen["D"] == "Colin Allred" and sen["R"] == "Ted Cruz"


def test_tx_fort_bend_party_prefix():
    df = T.county_xml("Fort Bend", xml("TX/detailxml_Fort_Bend_127480.zip"))
    sen = df[df["race"] == "SEN-TX"].groupby("party")["candidate"].first()
    assert sen["D"] == "JAMES TALARICO" and sen["R"] == "KEN PAXTON"


def test_tx_vote_types():
    assert T._vt("PROV/EV/ED") == "provisional" and T._vt("EV Mail") == "mail" and T._vt("EV In-person") == "early"
    assert T._vt("Early Voting Provisionals") == "provisional"
    assert T._vt("ED Provisional") == "provisional"
    assert T._vt("Ballot by Mail") == "mail" and T._vt("Absentee") == "mail" and T._vt("Vote by Mail") == "mail"
    assert T._vt("Early Voting In-Person") == "early" and T._vt("Early") == "early"
    assert T._vt("Election") == "election_day" and T._vt("Election Day In-Person") == "election_day"
    assert T._vt("regVotersCounty") is None and T._vt("Undervotes") is None


def test_tx_counties_skips_a_failing_county_and_raises_if_none_work(monkeypatch):
    good = T.county_xml("Denton", xml("TX/detailxml_Denton_127398.zip"))
    fail = {"El Paso"}

    def fake(county, eid, candidates=None, expect_date=None):
        if county in fail:
            raise RuntimeError("boom")
        return good.assign(county=f"{county} County")

    monkeypatch.setattr(T, "clarity_county", fake)
    monkeypatch.setattr(T, "_last_good", {})
    src = {"Denton": {"clarity": 1}, "El Paso": {"clarity": 2}, "Travis": {"clarity": None},
           "Harris": {"skip": True}, "Collin": None, "Bexar": 12345}
    df = T.tx_counties(src)
    assert set(df["county"]) == {"Denton County"}
    assert "boom" in T.last_errors["El Paso"] and T.last_errors["Travis"] == "no 2026 id yet"
    assert "Bexar" in T.last_errors and "Collin" not in T.last_errors    # malformed entry: that county only
    assert "El Paso" in df.attrs["warning"] and "Bexar" in df.attrs["warning"]
    assert "Travis" not in df.attrs["warning"]                           # waiting for an id isn't a failure
    # a county that worked once and then fails keeps its last rows, and is flagged
    fail.clear()
    T.tx_counties({"El Paso": {"clarity": 2}})
    fail.add("El Paso")
    df = T.tx_counties({"Denton": {"clarity": 1}, "El Paso": {"clarity": 2}})
    assert set(df["county"]) == {"Denton County", "El Paso County"}
    assert "keeping its file" in df.attrs["warning"]
    clean = T.tx_counties({"Denton": {"clarity": 1}, "Travis": {"clarity": None}})
    assert "warning" not in clean.attrs
    monkeypatch.setattr(T, "_last_good", {})
    with pytest.raises(RuntimeError, match="no Texas county feed"):
        T.tx_counties({"El Paso": {"clarity": 2}})
    with pytest.raises(RuntimeError, match="no Texas county feed"):
        T.tx_counties({"Travis": {"clarity": None}})


def test_tx_wrong_county_or_layout_fails_loudly():
    body = xml("TX/detailxml_Williamson_127488.zip")
    with pytest.raises(RuntimeError, match="Williamson County's"):
        T.county_xml("Denton", body)                       # Williamson's id pasted under Denton
    with pytest.raises(RuntimeError, match="not a Texas county"):
        T.county_xml("Williamsn", body.replace(b"<Region>Williamson", b"<Region>Williamsn"))
    with pytest.raises(RuntimeError, match="layout changed"):
        T.county_xml("Williamson", body.replace(b'text="United States', b'text="Unknown').replace(b'text="Governor"', b'text="X"'))


def test_tx_total_next_to_split_is_not_double_counted():
    df = T.county_xml("Denton", xml("TX/detailxml_Denton_122426.zip"), T.CANDIDATES_2024)
    doubled = pd.concat([df, df.groupby(["state", "fips", "county", "race", "party", "candidate"], as_index=False)
                         .agg(votes=("votes", "sum"), ts=("ts", "max"), complete=("complete", "all"))
                         .assign(vote_type="total")[df.columns]])
    fitted = T._fit_types(doubled)
    assert fitted["votes"].sum() == df["votes"].sum() and "total" not in set(fitted["vote_type"])


def test_same_date():
    assert F.same_date("11/3/2026", "11/03/2026") and F.same_date("11/3/2026 12:00:00 AM", "11/3/2026")
    assert not F.same_date("11/5/2024", "11/3/2026") and not F.same_date("", "11/3/2026")


def test_clarity_refuses_a_file_without_senate_rows(monkeypatch):
    zipped = (SAMPLES / "IA/detailxml_122322_2024.zip").read_bytes()   # right "date", no Senate race in IA 2024
    monkeypatch.setattr(F, "fetch", lambda url, **kw: b"1" if url.endswith("current_ver.txt") else zipped)
    with pytest.raises(RuntimeError, match="no U.S. Senate rows"):
        F.clarity("IA", "122322", expect_date="11/5/2024")
    assert len(F.clarity("IA", "122322")) > 0                           # no check without expect_date


def test_tx_vote_type_leans_reach_expected_vote():
    from midterms.live.baselines import expected_vote
    e = expected_vote("TX")
    denton = e[e["fips"] == "48121"].set_index("vote_type")
    assert set(denton.index) == {"early", "election_day", "mail"}
    assert denton.loc["mail", "lean"] > 20                               # mail ran ~26 pts bluer than Denton
    assert denton["expected"].sum() == pytest.approx(317778, rel=1e-3)   # Denton's 2022 total, split by 2024 shares
    assert set(e[e["fips"] == "48491"]["vote_type"]) == {"total"}       # Williamson: no leans


def test_mi_expected_vote_unchanged():
    from midterms.live.baselines import expected_vote
    e = expected_vote("MI")
    assert set(e[e["fips"] == "26125"]["vote_type"]) == {"early", "election_day", "mail"}
    assert set(e[e["fips"] == "26163"]["vote_type"]) == {"total"}       # Wayne


def test_tx_sources_file():
    src = T.load_sources()
    assert src["Denton"]["clarity"] == 127398
    assert src["Williamson"]["clarity"] == 127488
    assert src["El Paso"]["clarity"] == 127348
    assert src["Dallas"]["clarity"] == 127396 and src["Tarrant"]["clarity"] == 127297
    assert T._clarity_id("Fort Bend", src["Fort Bend"]["clarity"]) == ("Fort_Bend", "127480")


def test_tx_adapter_is_the_county_feed(monkeypatch):
    monkeypatch.setattr(T, "tx_counties", lambda: pd.DataFrame({"x": [1]}))
    assert list(F.ADAPTERS["TX"]()["x"]) == [1]


def test_clarity_url_ids():
    assert T._clarity_id("El Paso", 127348) == ("El_Paso", "127348")
    url = "https://results.enr.clarityelections.com/TX/Travis/128000/web.345435/#/summary"
    assert T._clarity_id("Travis", url) == ("Travis", "128000")


def test_engine_shows_a_failing_county_as_partial():
    import threading

    from midterms.live.engine import Engine
    e = Engine.__new__(Engine)   # only the feed loop's state, no markets or logs
    e.stop, e.lock, e.frames, e.results_version, e.feed_every = threading.Event(), threading.Lock(), {}, 0, 0
    e.feed_status = {"TX": dict(state="TX", status="starting")}
    df = T.county_xml("Denton", xml("TX/detailxml_Denton_127398.zip"))
    df.attrs["warning"] = "county failing: El Paso: boom"

    def fn():
        e.stop.set()
        return df

    e._feed_loop("TX", fn)
    st = e.feed_status["TX"]
    assert st["status"] == "partial" and "El Paso" in st["error"] and "TX" in e.frames


def test_tx_votes_must_add_up_to_the_files_total():
    body = xml("TX/detailxml_Denton_122426.zip")
    T.county_xml("Denton", body, T.CANDIDATES_2024)                      # the real file adds up
    broken = body.replace(b'name="Absentee"', b'name="Overvotes"', 1)   # first candidate loses its mail votes
    with pytest.raises(RuntimeError, match="vote types add to"):
        T.county_xml("Denton", broken, T.CANDIDATES_2024)                # a type silently dropped


def _rows(fips, county, race, cand, types):
    return pd.DataFrame([dict(state="TX", fips=fips, county=county, race=race, party="D", candidate=cand,
                              vote_type=t, votes=v, ts=None, complete=False) for t, v in types.items()])


def test_tx_fit_types_per_candidate():
    df = pd.concat([_rows("48121", "Denton County", "SEN-TX", "A", {"early": 10, "mail": 5, "total": 15}),
                    _rows("48121", "Denton County", "GOV-TX", "B", {"total": 7})])
    out = T._fit_types(df)
    assert out.groupby("race")["votes"].sum().to_dict() == {"SEN-TX": 15, "GOV-TX": 7}   # governor total kept
    # Tarrant has no provisional lean: provisional joins Election Day, the split stays
    t = T._fit_types(_rows("48439", "Tarrant County", "SEN-TX", "A", {"early": 10, "election_day": 4, "provisional": 1}))
    assert t.set_index("vote_type")["votes"].to_dict() == {"early": 10, "election_day": 5}
    assert "note" not in t.attrs
    # an unmeasured type in a county with leans: folded to total, and flagged
    u = T._fit_types(_rows("48439", "Tarrant County", "SEN-TX", "A", {"early": 10, "other": 3}))
    assert set(u["vote_type"]) == {"total"} and u["votes"].sum() == 13 and "Tarrant" in u.attrs["note"]
    # Williamson has no leans at all: folded quietly
    w = T._fit_types(_rows("48491", "Williamson County", "SEN-TX", "A", {"early": 10, "mail": 3}))
    assert set(w["vote_type"]) == {"total"} and "note" not in w.attrs


def test_tx_last_good_is_only_reused_for_the_same_id(monkeypatch):
    good = T.county_xml("Denton", xml("TX/detailxml_Denton_127398.zip"))
    state = {"fail": False}

    def fake(county, eid, candidates=None, expect_date=None):
        if state["fail"]:
            raise RuntimeError("boom")
        return good

    monkeypatch.setattr(T, "clarity_county", fake)
    monkeypatch.setattr(T, "_last_good", {})
    T.tx_counties({"Denton": {"clarity": 1}, "Dallas": {"clarity": 9}})
    state["fail"] = True
    with pytest.raises(RuntimeError, match="no Texas county feed"):
        T.tx_counties({"Denton": {"clarity": 2}})                          # a new id: the old rows aren't served


def test_tx_leans_move_a_mail_and_early_count_toward_the_republican():
    from midterms.live.project import project_race
    from midterms.live.replay import expected_2024
    rows = pd.concat([T.county_xml(c, xml(f"TX/detailxml_{f}.zip"), T.CANDIDATES_2024)
                      for c, f in [("Dallas", "Dallas_122494"), ("Tarrant", "Tarrant_122489"), ("Denton", "Denton_122426"),
                                   ("Fort Bend", "Fort_Bend_122596"), ("El Paso", "El_Paso_122595")]])
    rows = rows[(rows["race"] == "PRES-TX") & rows["vote_type"].isin(["early", "mail"])].assign(complete=False)
    exp = expected_2024("TX")
    with_leans = project_race(rows, "TX", -7.0, 4.9, baseline_col="margin20", expected=exp, race="PRES-TX")
    no_leans = project_race(rows, "TX", -7.0, 4.9, baseline_col="margin20", expected=exp.assign(lean=0.0), race="PRES-TX")
    assert with_leans.status == "projected"
    assert with_leans.margin < no_leans.margin < -7.0                     # 2024 truth: R+13.7


# ---- Harris (its own JSON) --------------------------------------------------------------

def harris(name: str) -> bytes:
    return (SAMPLES / "TX" / name).read_bytes()


def test_harris_2026_placeholder():
    df = T.harris_json(harris("harris_1126_2026-11-02.json"), expect_date="11/3/2026", code="1126")
    assert {"SEN-TX", "GOV-TX", "TX-02", "TX-07", "TX-18", "TX-38"} <= set(df["race"])
    assert set(df["fips"]) == {"48201"} and df["votes"].sum() == 0
    assert set(df["vote_type"]) == {"early", "election_day", "mail", "provisional"}
    sen = df[df["race"] == "SEN-TX"].groupby("party")["candidate"].first()
    assert sen["D"].title() == "James Talarico" and sen["R"].title() == "Ken Paxton"


def test_harris_2024_matches_baseline_and_keeps_every_vote():
    df = T.harris_json(harris("harris_1124_2024.json"), T.CANDIDATES_2024, expect_date="11/5/2024", code="1124")
    p = df[df["race"] == "PRES-TX"]
    g = p.groupby("party")["votes"].sum()
    b = county_baseline("TX").set_index("fips").loc["48201"]
    assert g["D"] == b["pres2024_dem"] and g["R"] == b["pres2024_gop"]   # ab+ev+ed+remainder == tv
    assert p["complete"].all()


def test_harris_refuses_another_election():
    with pytest.raises(RuntimeError, match="not 11/3/2026"):
        T.harris_json(harris("harris_1124_2024.json"), expect_date="11/3/2026")
    with pytest.raises(RuntimeError, match="not 1126"):
        T.harris_json(harris("harris_1124_2024.json"), code="1126")


def test_harris_in_sources_and_dispatch(monkeypatch):
    assert T.load_sources()["Harris"]["harris"] == 1126
    got = []
    monkeypatch.setattr(T, "harris", lambda code, c=None, e=None: got.append(code) or
                        T.harris_json(harris("harris_1126_2026-11-02.json")))
    monkeypatch.setattr(T, "_last_good", {})
    df = T.tx_counties({"Harris": {"harris": 1126}})
    assert got == [1126] and set(df["county"]) == {"Harris County"}


def _harris_edit(name: str, fn) -> bytes:
    d = json.loads(harris(name).decode("utf-8-sig"))
    fn(d)
    return json.dumps(d).encode()


def test_harris_refuses_malformed_arrays():
    def drop_early(d):
        next(c for c in d["contests"] if c["t"] == "United States Senator")["ev"] = []
    with pytest.raises(RuntimeError, match="different lengths"):
        T.harris_json(_harris_edit("harris_1124_2024.json", drop_early))

    def negative(d):
        next(c for c in d["contests"] if c["t"] == "United States Senator")["ab"][0] = -5
    with pytest.raises(RuntimeError, match="negative"):
        T.harris_json(_harris_edit("harris_1124_2024.json", negative))


def test_harris_skips_the_unexpired_term_house_contest():
    df = T.harris_json(harris("harris_1124_2024.json"), T.CANDIDATES_2024)
    d = json.loads(harris("harris_1124_2024.json").decode("utf-8-sig"))
    regular = next(c for c in d["contests"] if c["t"] == "United States Representative, District 18")
    assert df[df["race"] == "TX-18"]["votes"].sum() == sum(regular["tv"])


def test_harris_long_party_label():
    def spell_out(d):
        c = next(c for c in d["contests"] if c["t"] == "United States Representative, District 2")
        c["ca"] = [x.replace("(REP)", "(REPUBLICAN)") for x in c["ca"]]
    df = T.harris_json(_harris_edit("harris_1124_2024.json", spell_out), T.CANDIDATES_2024)
    assert "R" in set(df[df["race"] == "TX-02"]["party"])


def test_harris_refuses_an_older_file(monkeypatch):
    new = _harris_edit("harris_1126_2026-11-02.json", lambda d: d.update(dt="2026-11-04T05:00:00Z"))
    old = harris("harris_1126_2026-11-02.json")                          # stamped 2026-09-17
    bodies = iter([new, old])
    monkeypatch.setattr(T, "fetch", lambda url, **kw: next(bodies))
    monkeypatch.setattr(T, "_harris_last_time", {})
    T.harris(1126)
    with pytest.raises(RuntimeError, match="older than"):
        T.harris(1126)
