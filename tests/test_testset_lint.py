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
        "repaired_by": None,
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


def test_lektor_negative_needs_anchor(tmp_path):
    negative = dict(_case(tmp_path, kind="negativ", forbidden_claim="x", anchor=None),
                    expected_defect=None, expected_category=None, expected_severity=None)
    assert lint.lint([negative], tmp_path) == ["L-C13: lektor negativ case without anchor"]
    angreifer = negative | {"id": "R-C13", "suite": "angreifer"}
    assert lint.lint([angreifer], tmp_path) == []


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


def test_manifest_entry_holds_only_titel_gesetzentwurf_and_optional_inputs(tmp_path):
    """Every draft is sent whole; an extra key such as sections is rejected."""
    case = _case(tmp_path, id="R-X1", suite="angreifer", expected_category="schwellenwert")
    entry = {"titel": "T", "gesetzentwurf": case["text"]}
    assert lint.check_manifest({"21/537": entry}, [case], tmp_path) == []
    assert lint.check_manifest({"21/537": entry | {"sections": [[0, 5]]}}, [case], tmp_path) == [
        "inputs.yaml: 21/537 must hold titel and gesetzentwurf, "
        "optionally beschlussempfehlungen and bestandsrecht"]


def test_split_is_dev_or_test(tmp_path):
    assert any("split 'holdout'" in e
               for e in lint.check_case(_case(tmp_path, split="holdout"), tmp_path, {}))


def _pinned(texts, **overrides):
    """A Bestandsrecht case on 21/537 and a manifest entry pinning one norm for it."""
    case = _case(texts, requires_context="bestandsrecht")
    (texts / "bestandsrecht").mkdir(exist_ok=True)
    norm = "§ 44a Titel\n(1) Satz.\n"
    (texts / "bestandsrecht" / "AufenthG-44a.txt").write_text(norm, encoding="utf-8")
    excerpt = {"gesetz": "AufenthG", "norm": "§ 44a", "fassung": "2025-06-23",
               "herkunft": "GII", "cases": ["L-C13"], "file": "bestandsrecht/AufenthG-44a.txt",
               "sha256": hashlib.sha256(norm.encode()).hexdigest()} | overrides
    manifest = {"21/537": {"titel": "T", "gesetzentwurf": case["text"], "bestandsrecht": [excerpt]}}
    return case, manifest


def test_pinned_bestandsrecht_passes_and_is_allowed_in_the_manifest(tmp_path):
    case, manifest = _pinned(tmp_path)
    assert lint.check_bestandsrecht(manifest, [case], tmp_path) == []
    assert lint.check_manifest(manifest, [case], tmp_path) == []


def test_bestandsrecht_hash_and_case_ids_are_checked(tmp_path):
    other = _case(tmp_path, id="L-X", doc="21/9")
    plain = _case(tmp_path, id="L-Y")
    case, manifest = _pinned(tmp_path, sha256="0" * 64, cases=["L-C13", "L-?", "L-X", "L-Y"])
    assert lint.check_bestandsrecht(manifest, [case, other, plain], tmp_path) == [
        "inputs.yaml: 21/537 bestandsrecht[0] sha256 mismatch for bestandsrecht/AufenthG-44a.txt",
        "inputs.yaml: 21/537 bestandsrecht[0] names unknown case L-?",
        "inputs.yaml: 21/537 bestandsrecht[0] names L-X of another document",
        "inputs.yaml: 21/537 bestandsrecht[0] names L-Y, which does not require bestandsrecht"]


def test_every_bestandsrecht_case_needs_an_excerpt_and_every_file_one_entry(tmp_path):
    case, manifest = _pinned(tmp_path)
    (tmp_path / "bestandsrecht" / "StAG-10.txt").write_text("x", encoding="utf-8")
    del manifest["21/537"]["bestandsrecht"]
    assert lint.check_bestandsrecht(manifest, [case], tmp_path) == [
        "L-C13: requires bestandsrecht but no excerpt in inputs.yaml",
        "bestandsrecht/AufenthG-44a.txt: text file used by no excerpt",
        "bestandsrecht/StAG-10.txt: text file used by no excerpt"]


def test_missing_bestandsrecht_file_is_not_fetchable(tmp_path):
    case, manifest = _pinned(tmp_path, file="bestandsrecht/Fehlt-1.txt")
    errors = lint.check_bestandsrecht(manifest, [case], tmp_path)
    assert ("inputs.yaml: 21/537 bestandsrecht[0] bestandsrecht/Fehlt-1.txt missing "
            "(pinned by hand, not fetchable)") in errors


def _committee(texts, **overrides):
    """A case repaired by 21/1634 and a manifest entry pinning that Beschlussempfehlung."""
    case = _case(texts, repaired_by="21/1634")
    (texts / "beschlussempfehlung").mkdir(exist_ok=True)
    report = "Beschlussempfehlung und Bericht\n"
    (texts / "beschlussempfehlung" / "21-1634.txt").write_text(report, encoding="utf-8")
    pin = {"doc": "21/1634", "file": "beschlussempfehlung/21-1634.txt",
           "sha256": hashlib.sha256(report.encode()).hexdigest()} | overrides
    manifest = {"21/537": {"titel": "T", "gesetzentwurf": case["text"],
                           "beschlussempfehlungen": [pin]}}
    return case, manifest


def test_pinned_beschlussempfehlung_passes_and_is_allowed_in_the_manifest(tmp_path):
    case, manifest = _committee(tmp_path)
    assert lint.check_beschlussempfehlungen(manifest, [case], {"L-C13"}, tmp_path) == []
    assert lint.check_manifest(manifest, [case], tmp_path) == []
    assert lint.lint([case], tmp_path) == []


def test_beschlussempfehlung_hash_name_and_repaired_by_are_checked(tmp_path):
    case, manifest = _committee(tmp_path, sha256="0" * 64)
    unknown = _case(tmp_path, id="L-X", repaired_by="21/9999")
    missing = _case(tmp_path, id="L-Y")
    (tmp_path / "beschlussempfehlung" / "21-1.txt").write_text("x", encoding="utf-8")
    assert lint.check_beschlussempfehlungen(
        manifest, [case, unknown, missing], {"L-Y"}, tmp_path) == [
        "inputs.yaml: 21/537 beschlussempfehlungen[0] sha256 mismatch for "
        "beschlussempfehlung/21-1634.txt",
        "L-X: repaired_by 21/9999 not among the beschlussempfehlungen of its document "
        "in inputs.yaml",
        "L-Y: without repaired_by",
        "beschlussempfehlung/21-1.txt: text file used by no entry"]
    _, renamed = _committee(tmp_path, file="21-1634.txt")
    assert ("inputs.yaml: 21/537 beschlussempfehlungen[0] file must be "
            "beschlussempfehlung/<Drucksache>.txt") in lint.check_beschlussempfehlungen(
        renamed, [case], set(), tmp_path)


def test_repaired_by_is_a_drucksache_on_a_positive(tmp_path):
    assert lint.check_case(_case(tmp_path, repaired_by="BE"), tmp_path, {}) == [
        "L-C13: repaired_by 'BE' is not a Drucksache number"]
    negative = _case(tmp_path, kind="negativ", repaired_by="21/1634", forbidden_claim="x",
                     expected_defect=None, expected_category=None, expected_severity=None)
    assert "L-C13: negativ case with repaired_by" in lint.check_case(negative, tmp_path, {})
