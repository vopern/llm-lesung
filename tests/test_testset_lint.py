import hashlib

from eval.testset import lint

TEXT = "Artikel 1\n§ 10 Absatz 3 wird ge-\nstrichen.\n"


def _case(texts, **overrides):
    """A valid positive against a text written into ``texts``."""
    (texts / "21-537.txt").write_text(TEXT, encoding="utf-8")
    case = {
        "id": "L-C13",
        "suite": "lektor",
        "doc": "21/537",
        "drucksachetyp": "Gesetzentwurf",
        "text": {"file": "21-537.txt", "sha256": hashlib.sha256(TEXT.encode()).hexdigest()},
        "kind": "positiv",
        "expected_passage": "Art. 1",
        "anchor": "§ 10 Absatz 3 wird gestrichen",
        "expected_defect": "keine Übergangsregel",
        "expected_category": "vollstaendigkeit",
        "expected_severity": "hoch",
        "requires_context": "none",
        "forbidden_claim": None,
        "split": "dev",
        "story": "Der Ausschuss strich § 10 Abs. 3, ohne Altfälle zu regeln.",
        "source": "Volltext geprüft.",
    }
    return case | overrides


def test_committed_testset_is_clean():
    cases = [c for path in lint.PATHS for c in lint.load(path)]
    assert cases
    assert lint.lint(cases) == []


def test_valid_case_passes_with_hyphenated_anchor(tmp_path):
    assert lint.lint([_case(tmp_path)], tmp_path) == []


def test_detects_broken_anchor_and_hash(tmp_path):
    case = _case(tmp_path, anchor="§ 10 Absatz 4 wird gestrichen")
    case["text"]["sha256"] = "0" * 64
    errors = lint.lint([case], tmp_path)
    assert "L-C13: sha256 mismatch for 21-537.txt" in errors
    assert "L-C13: anchor not found in 21-537.txt" in errors


def test_negative_needs_forbidden_claim_and_no_expectation(tmp_path):
    case = _case(tmp_path, kind="negativ")
    errors = lint.lint([case], tmp_path)
    assert "L-C13: negativ case without forbidden_claim" in errors
    assert "L-C13: negativ case with expected_defect" in errors


def test_positive_must_not_carry_forbidden_claim(tmp_path):
    errors = lint.lint([_case(tmp_path, forbidden_claim="x")], tmp_path)
    assert errors == ["L-C13: positive with forbidden_claim"]


def test_category_is_checked_against_the_suite(tmp_path):
    case = _case(tmp_path, id="R-C13", suite="angreifer")
    errors = lint.lint([case], tmp_path)
    assert errors == ["R-C13: expected_category 'vollstaendigkeit' unknown for angreifer"]


def test_duplicate_id_prefix_and_orphan_text(tmp_path):
    (tmp_path / "21-1.txt").write_text("x", encoding="utf-8")
    errors = lint.lint([_case(tmp_path), _case(tmp_path, id="C13")], tmp_path)
    assert "C13: id must start with L-" in errors
    assert "21-1.txt: text file used by no case" in errors
    assert lint.lint([_case(tmp_path), _case(tmp_path)], tmp_path)[0] == "L-C13: duplicate id"


def test_story_must_not_point_outside_the_test_set(tmp_path):
    case = _case(tmp_path, story="Siehe data/testcases-controversial-bills.md, C13.")
    assert lint.lint([case], tmp_path) == ["L-C13: story points outside the test set"]


def test_document_must_not_straddle_splits(tmp_path):
    cases = [_case(tmp_path), _case(tmp_path, id="L-C14", split="test")]
    assert lint.lint(cases, tmp_path) == ["21-537.txt: lektor cases in several splits ['dev', 'test']"]


def test_committed_yaml_carries_the_canary(tmp_path):
    assert lint.check_canary(lint.PATHS) == []
    bare = tmp_path / "cases.yaml"
    bare.write_text("- id: L-C13\n", encoding="utf-8")
    assert lint.check_canary([bare]) == ["cases.yaml: canary GUID missing"]


def test_manifest_entry_holds_only_titel_and_gesetzentwurf(tmp_path):
    """Every draft is sent whole; an extra key such as sections is rejected."""
    case = _case(tmp_path, id="R-X1", suite="angreifer", expected_category="schwellenwert")
    entry = {"titel": "T", "gesetzentwurf": case["text"]}
    assert lint.check_manifest({"21/537": entry}, [case], tmp_path) == []
    assert lint.check_manifest({"21/537": entry | {"sections": [[0, 5]]}}, [case], tmp_path) == [
        "inputs.yaml: 21/537 must hold titel and gesetzentwurf"]


def test_split_is_dev_or_test(tmp_path):
    assert any("split 'holdout'" in e
               for e in lint.check_case(_case(tmp_path, split="holdout"), tmp_path, {}))
