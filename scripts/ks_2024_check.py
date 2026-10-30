"""Check the Kansas county adapters (feeds.ks_county) on the 2024 general, presidential race.

    uv run python scripts/ks_2024_check.py

Fetches 15 files from the county sites through feeds.fetch (robots check, raw copies
under data/raw-live/), a few seconds apart. Shawnee is skipped: its files are on
cdn.snco.gov, whose robots.txt disallows all agents. Prints
1. final reports against county_baseline (pres2024_dem / _gop / _total; the baseline's
   total leaves out write-ins);
2. the Sedgwick and Johnson update sequences (totals should only grow);
3. project_race on four election-night snapshots of these counties only.
"""

from __future__ import annotations

import time

import pandas as pd

from midterms.live import feeds as F
from midterms.live.baselines import county_baseline
from midterms.live.project import project_race
from midterms.live.replay import expected_2024

PRES = dict(race_pattern=r"PRESIDENT", candidates={"D": ("Harris",), "R": ("Trump",)}, race="PRES-KS")
JOCO = "https://jocoelection.org/sites/default/files/2024-11/GN2024%20"
SEDG = "https://www.sedgwick.gov/media/"
DOUG_FINAL = "https://www.livevoterturnout.com/ENR/douglasksenr/18/en/Index_18.html"
JOHNSON = {"advance": JOCO + "Advance%20Results.pdf", "update 1": JOCO + "Unofficial%20Results%20Update%201.pdf",
           "election-night final": JOCO + "Unofficial%20Final%20Results.pdf",
           "thursday": JOCO + "Unofficial%20Final%20Results%20Thursday%20Update.pdf",
           "official": JOCO + "Official%20Final%20Results.pdf"}
SEDGWICK = {"1st (advance)": SEDG + "67672/2024-general-1st-unofficial-results-advance.pdf",
            "2nd": SEDG + "67673/2024-general-2nd-unoffical-results.pdf",
            "3rd": SEDG + "67674/2024-general-3rd-unofficial-results.pdf",
            "4th": SEDG + "67675/2024-general-4th-unofficial-results.pdf",
            "election-night final": SEDG + "67676/2024-general-final-unoffical-election-night-results.pdf",
            "wednesday": SEDG + "67681/2024-general-wed-unofficial-results.pdf",
            "official": SEDG + "67739/2024-general-official-results.pdf"}
PAUSE = 3.0


def get(county: str, url: str) -> pd.DataFrame:
    df = F.ks_county(county, url, label=url, **PRES)
    time.sleep(PAUSE)
    return df


def tot(df: pd.DataFrame) -> dict:
    g = df.groupby("party")["votes"].sum()
    wi = df.loc[df["candidate"].str.lower().str.startswith("write"), "votes"].sum()
    return dict(D=int(g.get("D", 0)), R=int(g.get("R", 0)), all=int(g.sum()), ex_writein=int(g.sum() - wi),
                complete=bool(df["complete"].all()) if len(df) else False)


def main() -> None:
    base = county_baseline("KS").set_index("key")
    seq = {"Johnson": {k: get("Johnson", u) for k, u in JOHNSON.items()},
           "Sedgwick": {k: get("Sedgwick", u) for k, u in SEDGWICK.items()}}
    doug = get("Douglas", DOUG_FINAL)

    print("\n1. Final official reports vs county_baseline('KS')")
    finals = {"Johnson": seq["Johnson"]["official"], "Sedgwick": seq["Sedgwick"]["official"], "Douglas": doug}
    out = []
    for c, df in finals.items():
        t, b = tot(df), base.loc[c.upper()]
        out.append(dict(county=c, D=t["D"], base_D=int(b["pres2024_dem"]), R=t["R"], base_R=int(b["pres2024_gop"]),
                        total_ex_writein=t["ex_writein"], base_total=int(b["pres2024_total"]), write_ins=t["all"] - t["ex_writein"],
                        vote_types=",".join(sorted(df["vote_type"].unique()))))
    print(pd.DataFrame(out).to_string(index=False))
    print("   (Shawnee: not fetchable, cdn.snco.gov robots.txt disallows all agents)")

    print("\n2. Update sequences (cumulative; share of the official total)")
    for c, reports in seq.items():
        rows, prev = [], -1
        off = tot(reports["official"])["all"]
        for k, df in reports.items():
            t = tot(df)
            rows.append(dict(county=c, report=k, D=t["D"], R=t["R"], total=t["all"], of_official=f"{t['all'] / off:.1%}",
                             margin=f"{100 * (t['D'] - t['R']) / t['all']:+.1f}", complete=t["complete"],
                             grows=t["all"] >= prev))
            prev = t["all"]
        print(pd.DataFrame(rows).to_string(index=False))

    print("\n3. project_race on these counties only (prior = 2024 polling average, D-R -8.3, SD 4.9;"
          " baseline margin20; expected = 2020 turnout; actual KS result -16.1)")
    snaps = {"advance only (JoCo advance + Sedgwick 2nd)": [seq["Johnson"]["advance"], seq["Sedgwick"]["2nd"]],
             "mid-count (JoCo update 1 + Sedgwick 3rd)": [seq["Johnson"]["update 1"], seq["Sedgwick"]["3rd"]],
             "election-night finals + Douglas": [seq["Johnson"]["election-night final"],
                                                  seq["Sedgwick"]["election-night final"], doug],
             "official, three counties": [seq["Johnson"]["official"], seq["Sedgwick"]["official"], doug]}
    exp = expected_2024("KS")
    rows = []
    for name, frames in snaps.items():
        df = pd.concat(frames, ignore_index=True)
        p = project_race(df, "KS", -8.333, 4.9, baseline_col="margin20", expected=exp, race="PRES-KS")
        rows.append(dict(snapshot=name, status=p.status, share_in=f"{p.share_in:.1%}", margin=round(p.margin, 2),
                         sd=round(p.sd, 2), p_dem=round(p.p_d, 4), swing=round(p.swing, 2),
                         finished=p.info.get("finished_counties"), sources=p.info.get("source_swings"),
                         turnout=p.info.get("turnout")))
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
