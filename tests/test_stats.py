import numpy as np
import pandas as pd
import pytest
from scipy import stats as st

from nucleiquant import stats


def test_holm_known_values():
    # Classic example: p = 0.01, 0.04, 0.03, 0.005 (m = 4)
    adj = stats.holm([0.01, 0.04, 0.03, 0.005])
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_dunn_matches_formula():
    groups = {"A": [1.0, 2, 3, 4], "B": [5.0, 6, 7, 8], "C": [9.0, 10, 11, 12]}
    res = {(a, b): (z, p) for a, b, z, p in stats.dunn(groups)}
    # No ties: mean ranks 2.5, 6.5, 10.5; sigma = sqrt(12*13/12 * (1/4+1/4))
    sigma = np.sqrt(12 * 13 / 12 * 0.5)
    z = (2.5 - 10.5) / sigma
    assert res[("A", "C")][0] == pytest.approx(z)
    assert res[("A", "C")][1] == pytest.approx(2 * st.norm.sf(abs(z)))


def test_compare_two_groups_uses_mann_whitney():
    df = pd.DataFrame({"Genotype": ["WT"] * 5 + ["KO"] * 5, "S": [10, 12, 11, 13, 12, 30, 31, 29, 33, 32.0]})
    rows, warnings = stats.compare_groups(df, "Genotype", ["S"], "% of living cells")
    assert rows[0]["Test"] == "Mann-Whitney U"
    ref = st.mannwhitneyu(df.S[:5], df.S[5:], alternative="two-sided").pvalue
    assert rows[0]["p"] == pytest.approx(ref)
    assert not warnings


def test_compare_three_groups_and_small_group_warning():
    df = pd.DataFrame({"G": ["a", "a", "b", "b", "c", "c"], "N": [1, 2, 5, 6, 9, 10.0]})
    rows, warnings = stats.compare_groups(df, "G", ["N"], "% of living cells")
    assert rows[0]["Test"] == "Kruskal-Wallis"
    assert "Dunn (Holm)" in rows[0]
    assert any("Fewer than 3" in w for w in warnings)


def test_single_group():
    df = pd.DataFrame({"G": ["a", "a"], "N": [1, 2.0]})
    rows, warnings = stats.compare_groups(df, "G", ["N"], "x")
    assert rows == [] and "Only one group" in warnings[0]
