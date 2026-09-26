"""Group comparisons of per-organoid proportions.

The unit of replication is the organoid (never the cell). Two groups:
Mann-Whitney U. Three or more: Kruskal-Wallis, then Dunn's pairwise test.
p-values are Holm-corrected across categories (omnibus tests) and across
pairs (Dunn).
"""

import itertools

import numpy as np
from scipy import stats as st

__all__ = ["holm", "dunn", "compare_groups", "stars"]


def holm(pvalues):
    """Holm-Bonferroni adjusted p-values (same order as the input)."""
    p = np.asarray(pvalues, dtype=float)
    out = np.full(p.shape, np.nan)
    ok = np.isfinite(p)
    idx = np.flatnonzero(ok)
    if len(idx) == 0:
        return out
    order = idx[np.argsort(p[idx])]
    m = len(order)
    running = 0.0
    for k, i in enumerate(order):
        running = max(running, min(1.0, (m - k) * p[i]))
        out[i] = running
    return out


def dunn(groups):
    """Dunn's test for all pairs. groups: dict name -> values.

    Returns a list of (group_a, group_b, z, p) with two-sided p-values
    (not adjusted), using average ranks and the tie correction.
    """
    names = list(groups)
    values = np.concatenate([np.asarray(groups[g], float) for g in names])
    ranks = st.rankdata(values)
    N = len(values)
    _, tie_counts = np.unique(values, return_counts=True)
    tie = np.sum(tie_counts ** 3 - tie_counts) / (12.0 * (N - 1)) if N > 1 else 0.0
    mean_rank, sizes = {}, {}
    start = 0
    for g in names:
        n = len(groups[g])
        mean_rank[g] = ranks[start:start + n].mean()
        sizes[g] = n
        start += n
    out = []
    for a, b in itertools.combinations(names, 2):
        sigma = np.sqrt((N * (N + 1) / 12.0 - tie) * (1.0 / sizes[a] + 1.0 / sizes[b]))
        z = (mean_rank[a] - mean_rank[b]) / sigma if sigma > 0 else 0.0
        p = 2 * st.norm.sf(abs(z))
        out.append((a, b, float(z), float(p)))
    return out


def stars(p):
    if p is None or not np.isfinite(p):
        return ""
    return "****" if p < 1e-4 else "***" if p < 1e-3 else "**" if p < 1e-2 else "*" if p < 0.05 else "ns"


def compare_groups(table, group_col, outcomes, measure_label):
    """Compare groups for each outcome column of a per-organoid table.

    Returns (rows, warnings). Each row is a dict ready for a DataFrame.
    """
    rows, warnings = [], []
    groups = [g for g in sorted(table[group_col].dropna().unique()) if g != ""]
    if len(groups) < 2:
        return rows, ["Only one group: nothing to compare."]
    sizes = {g: int((table[group_col] == g).sum()) for g in groups}
    small = [g for g, n in sizes.items() if n < 3]
    if small:
        warnings.append(
            "Fewer than 3 organoids in " + ", ".join(map(str, small))
            + ": tests have very little power (with 2 vs 2, p can never go below 0.33)."
        )
    omnibus = []
    for col in outcomes:
        data = {g: table.loc[table[group_col] == g, col].dropna().to_numpy(float) for g in groups}
        data = {g: v for g, v in data.items() if len(v) > 0}
        row = {
            "Measure": measure_label, "Category": col, "Groups": " vs ".join(map(str, data)),
            "n per group": ", ".join(f"{g}: {len(v)}" for g, v in data.items()),
            "Median per group": ", ".join(f"{g}: {np.median(v):.2f}" for g, v in data.items()),
        }
        if len(data) < 2:
            row.update({"Test": "", "Statistic": np.nan, "p": np.nan})
        elif len(data) == 2:
            a, b = data.values()
            if np.all(np.concatenate([a, b]) == a[0]):
                row.update({"Test": "Mann-Whitney U", "Statistic": np.nan, "p": 1.0})
            else:
                res = st.mannwhitneyu(a, b, alternative="two-sided")
                row.update({"Test": "Mann-Whitney U", "Statistic": float(res.statistic), "p": float(res.pvalue)})
        else:
            allv = np.concatenate(list(data.values()))
            if np.all(allv == allv[0]):
                row.update({"Test": "Kruskal-Wallis", "Statistic": np.nan, "p": 1.0})
            else:
                res = st.kruskal(*data.values())
                row.update({"Test": "Kruskal-Wallis", "Statistic": float(res.statistic), "p": float(res.pvalue)})
                pairs = dunn(data)
                adj = holm([p for *_, p in pairs])
                row["Dunn (Holm)"] = "; ".join(
                    f"{a} vs {b}: p={pa:.3g} {stars(pa)}" for (a, b, _, _), pa in zip(pairs, adj)
                )
        rows.append(row)
        omnibus.append(row["p"])
    adj = holm(omnibus)
    for row, pa in zip(rows, adj):
        row["p (Holm)"] = float(pa) if np.isfinite(pa) else np.nan
        row["Significance"] = stars(pa)
    return rows, warnings
