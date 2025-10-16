# src/app/run_snapshot.py

import argparse
import pandas as pd

from core.novig import add_implied_prob, remove_vig
from core.consensus import consensus_fair
from core.bestprice import best_prices
from core.arb import find_arbs, stake_split
from feeds.aggregate import fetch_snapshot_all


def run_once() -> dict[str, pd.DataFrame]:
    raw = fetch_snapshot_all()
    if raw.empty:
        return {"raw": raw, "priced": pd.DataFrame(), "best": pd.DataFrame(), "arbs": pd.DataFrame()}

    with_probs = add_implied_prob(raw)
    novig = remove_vig(with_probs)
    fair = consensus_fair(novig)
    best = best_prices(novig, fair)
    arbs = find_arbs(best)

    # Nice display order
    best = best[
        ["event_id", "event", "market", "outcome", "best_book", "best_decimal", "fair_decimal", "edge_pct"]
    ].sort_values(["event_id", "outcome"]).reset_index(drop=True)

    return {"raw": raw, "priced": novig, "best": best, "arbs": arbs}


def main():
    parser = argparse.ArgumentParser(description="EPL 1X2 odds snapshot and value finder")
    parser.add_argument("--export", choices=["csv", "parquet"], help="Export results to files", default=None)
    parser.add_argument("--outdir", default=".", help="Directory to write exports to")
    parser.add_argument("--bank", type=float, default=100.0, help="Bank for arbitrage stake split previews")
    args = parser.parse_args()

    result = run_once()
    best = result.get("best", pd.DataFrame())
    arbs = result.get("arbs", pd.DataFrame())

    print("\nTop value spots (edge >= 1%):")
    if not best.empty:
        filt = best[best["edge_pct"] >= 1.0].copy()
        if filt.empty:
            print("(no edges ≥ 1% — showing all best prices instead)")
            print(best.to_string(index=False))
        else:
            print(filt.to_string(index=False))
    else:
        print("(no data)")

    print("\nArbitrage scans:")
    if not arbs.empty:
        print(arbs.to_string(index=False))
        any_arbs = arbs[arbs["is_arbitrage"]]
        if not any_arbs.empty:
            print("\nArbitrage stake plan previews:")
            for (eid, ev, mkt), grp in best.groupby(["event_id", "event", "market"]):
                row = arbs[(arbs["event_id"] == eid) & (arbs["market"] == mkt)]
                if not row.empty and bool(row["is_arbitrage"].iloc[0]):
                    plan = stake_split(grp, bank=args.bank)
                    print(f"\n{ev} — {mkt} (bank={args.bank})")
                    print(plan[["outcome", "best_book", "best_decimal", "stake", "const_payout", "roi_pct"]]
                          .to_string(index=False))
    else:
        print("(none)")

    if args.export:
        outdir = args.outdir.rstrip("/\\")
        paths = []
        for name, df in result.items():
            if df.empty:
                continue
            path = f"{outdir}/{name}.{args.export}"
            if args.export == "csv":
                df.to_csv(path, index=False)
            else:
                df.to_parquet(path, index=False)
            paths.append(path)
        if paths:
            print("\nExported:", *paths, sep="\n  ")


if __name__ == "__main__":
    main()
