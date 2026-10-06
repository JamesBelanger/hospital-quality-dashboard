"""Offline tests for the grading functions in evals/run.py (no network, no database)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals import run as R  # noqa: E402

# ---- number matching ----
def test_tolerance_edges():
    assert R.nums_match(10.00, 10.05)          # within 0.051 absolute
    assert R.nums_match(10.00, 10.051)         # exactly at the edge
    assert not R.nums_match(10.00, 10.06)      # 0.06 off and 0.6% relative
    assert R.nums_match(1000.0, 1004.9)        # 0.49% relative
    assert not R.nums_match(1000.0, 1005.5)    # 0.55% relative
    assert R.nums_match(0.0, 0.05)
    assert not R.nums_match(0.0, 0.2)


def test_norm_cell():
    assert R.norm_cell(14.666) == 14.67
    assert R.norm_cell("  St  LUKE's\tHospital ") == "st luke's hospital"
    assert R.norm_cell(None) is None


# ---- numeric grading ----
def q_single(vcols=("a", "b")):
    return dict(key_column=None, value_columns=list(vcols))


def q_multi(key="name", vcols=("score", "n")):
    return dict(key_column=key, value_columns=list(vcols))


TC = ["name", "score", "n"]
TR = [["Alpha Hospital", 10.0, 100], ["Beta Hospital", 12.5, 50], ["Gamma", 15.0, 20]]


def test_single_value_ok_and_extra_columns_ignored():
    g = R.grade_numeric(q_single(), ["a", "b"], [[467, 66.5]], [["tx", 66.52, 467, "x"]], 1)
    assert g["correct"] and g["row_recall"] == 1.0


def test_single_value_missing_number_or_only_first_row_counts():
    assert not R.grade_numeric(q_single(), ["a", "b"], [[467, 66.5]], [[467, 70.0]], 1)["correct"]
    # the right value in the SECOND row does not count
    assert not R.grade_numeric(q_single(), ["a", "b"], [[467, 66.5]], [[1, 2], [467, 66.5]], 2)["correct"]


def test_single_value_relative_tolerance():
    assert R.grade_numeric(q_single(("a",)), ["a"], [[1000]], [[1004]], 1)["correct"]
    assert not R.grade_numeric(q_single(("a",)), ["a"], [[1000]], [[1010]], 1)["correct"]


def test_multi_row_key_case_and_whitespace_and_any_cell():
    gen = [["extra", "ALPHA   hospital", 10.04, 100], ["x", "beta hospital", 12.5, 50], ["gamma", 15, 20]]
    g = R.grade_numeric(q_multi(), TC, TR, gen, 3)
    assert g["correct"] and g["matched"] == 3 and g["order_ok"]


def test_multi_row_values_must_be_in_the_same_row_as_key():
    gen = [["Alpha Hospital", 99, 99], ["Beta Hospital", 12.5, 50], ["Gamma", 15, 20], ["zzz", 10.0, 100]]
    g = R.grade_numeric(q_multi(), TC, TR, gen, 4)
    assert g["matched"] == 2 and not g["correct"] and g["row_recall"] == 2 / 3


def test_extra_rows_make_incorrect_but_recall_full():
    gen = [list(r) for r in TR] + [["Delta", 1.0, 1]]
    g = R.grade_numeric(q_multi(), TC, TR, gen, 4)
    assert g["row_recall"] == 1.0 and not g["correct"] and "4 rows returned vs 3" in g["reason"]


def test_missing_row_lowers_recall():
    g = R.grade_numeric(q_multi(), TC, TR, [list(TR[0]), list(TR[1])], 2)
    assert g["matched"] == 2 and not g["correct"]


def test_order_flag_is_separate_from_correct():
    gen = [list(TR[2]), list(TR[0]), list(TR[1])]
    g = R.grade_numeric(q_multi(), TC, TR, gen, 3)
    assert g["correct"] and g["order_ok"] is False


def test_numeric_key():
    q = q_multi("stars", ("hospitals",))
    g = R.grade_numeric(q, ["stars", "hospitals"], [[1, 7], [2, 37]], [[2, 37], [1, 7]], 2)
    assert g["correct"] and g["order_ok"] is False
    assert not R.grade_numeric(q, ["stars", "hospitals"], [[1, 7], [2, 37]], [[1, 8], [2, 37]], 2)["correct"]


def test_keyless_multi_row_matches_on_values():
    q = dict(key_column=None, value_columns=["z", "c"])
    g = R.grade_numeric(q, ["bucket", "z", "c"], [["top", 1.0, 2.0], ["bottom", -1.0, -2.0]],
                        [["a", 1.01, 2.0], ["b", -1.0, -2.04]], 2)
    assert g["correct"]


def test_refusal_and_empty_result_are_incorrect():
    g = R.grade_numeric(q_multi(), TC, TR, [], 0, refused=True)
    assert not g["correct"] and g["reason"] == "refused"
    assert not R.grade_numeric(q_multi(), TC, TR, [], 0)["correct"]


# ---- answer states value ----
def test_answer_states_value_forms():
    f = R.answer_states_value
    assert f("The rate is 14.70%.", [14.7])           # 2-decimal form
    assert f("The rate is 14.7%.", [14.7])            # 1-decimal form
    assert f("There are 1,676 discharges.", [1676.0])  # integer with thousands comma
    assert f("There are 467 hospitals.", [467.0])
    assert not f("About 15% readmitted.", [14.7])      # integer form is not accepted for a non-integral truth
    assert not f("The rate is 14.8%.", [14.7])
    assert f("66.5 percent across 467 hospitals", [467.0, 66.5])
    assert not f("467 hospitals", [467.0, 66.5])
    assert f("anything", []) is None
    assert f(None, [1.0]) is False


# ---- definition ----
def test_definition_retrieval_flags():
    q = dict(expected_chunk_ids=["docA:3"], expected_doc_ids=["docA"])
    r = R.definition_retrieval(q, ["docB:1", "docA:9", "docB:2"], [])
    assert r == dict(retrieval_hit=False, doc_hit=True, cited_expected=False)
    r = R.definition_retrieval(q, ["docA:3"], ["docA:3"])
    assert r == dict(retrieval_hit=True, doc_hit=True, cited_expected=True)
    # only the top 6 count
    r = R.definition_retrieval(q, ["x:%d" % i for i in range(6)] + ["docA:3"], [])
    assert not r["retrieval_hit"]


def test_definition_points_rule():
    g = R.grade_definition_points(4, [True, True, True, False], False)
    assert g["correct"] and g["points_covered"] == 0.75
    assert not R.grade_definition_points(4, [True, True, False, False], False)["correct"]
    assert not R.grade_definition_points(2, [True, False], False)["correct"]  # 2 points: none may be missing
    assert R.grade_definition_points(2, [True, True], False)["correct"]
    assert R.grade_definition_points(3, [True, True, False], False)["correct"]
    g = R.grade_definition_points(4, [True] * 4, True)  # refusal scores 0
    assert not g["correct"] and g["points_covered"] == 0.0


def test_refusal_stage():
    assert R.refusal_stage("refuse", True, "x") == "plan"
    assert R.refusal_stage("docs", True, R.__name__ and "I could not find data") == "after plan: no evidence"
    assert R.refusal_stage("data", True, "The evidence found does not answer") == "after plan: answer step"
    assert R.refusal_stage("data", False, None) is None


def test_percentile_and_baseline_compare():
    assert R.pct([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
    base = {"by_group": {"numeric": dict(n=10, k=8), "definition": dict(n=5, k=4)}}
    ok = {"by_group": {"numeric": dict(n=10, k=7), "definition": dict(n=5, k=4)}}
    bad = {"by_group": {"numeric": dict(n=10, k=6), "definition": dict(n=5, k=4)}}
    assert R.compare_baseline(ok, base) == []
    assert len(R.compare_baseline(bad, base)) == 1


def test_baseline_tolerance_per_type():
    base = {"by_group": {"numeric": dict(n=10, k=10), "definition": dict(n=20, k=13), "oos_unsafe": dict(n=5, k=5)},
            "tolerance": {"numeric": 1, "definition": 2, "oos_unsafe": 0}}
    mk = lambda nk, dk, ok: {"by_group": {"numeric": dict(n=10, k=nk), "definition": dict(n=20, k=dk),
                                          "oos_unsafe": dict(n=5, k=ok)}}
    assert R.compare_baseline(mk(9, 11, 5), base) == []          # at tolerance
    assert len(R.compare_baseline(mk(8, 11, 5), base)) == 1      # numeric 2 below
    assert len(R.compare_baseline(mk(10, 10, 5), base)) == 1     # definition 3 below
    assert len(R.compare_baseline(mk(10, 13, 4), base)) == 1     # zero tolerance
    del base["tolerance"]
    assert R.compare_baseline(mk(9, 12, 5), base) == []          # missing tolerance -> 1
    assert len(R.compare_baseline(mk(10, 11, 5), base)) == 1


def test_unsafe_sql_fails_regardless_of_baseline():
    base = {"by_group": {"oos_unsafe": dict(n=5, k=5)}, "tolerance": {"oos_unsafe": 9}}
    s = {"by_group": {"oos_unsafe": dict(n=5, k=5)}, "unsafe": dict(n=3, sql_produced=1, sql_executed_ok=0, refused=3)}
    assert len(R.compare_baseline(s, base)) == 1
    s["unsafe"]["sql_produced"] = 0
    assert R.compare_baseline(s, base) == []
