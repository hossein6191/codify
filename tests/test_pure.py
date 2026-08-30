"""The half of Codify that never asks anybody anything.

The most important test here is `TestBinding` — the one that shows why this
contract stores a catalogue entry rather than a generated program. An earlier
version had validators agree when the leader's code and their own produced the
same answers on the author's examples plus some generated mutations. A reviewer
pointed out that this does not bind: two programs can agree on every subject
anyone tried and differ on the next one, and it was the leader's program that
got stored and obeyed.

So the tests below check that the *whole policy* is pinned — every argument of
it — and that anything the catalogue cannot express is refused rather than
approximated.
"""

import sys
import types
import pathlib
import json

if "genlayer" not in sys.modules:
    stub = types.ModuleType("genlayer")

    class _Any:
        def __getattr__(self, n): return _Any()
        def __call__(self, *a, **k): return _Any()
        def __getitem__(self, n): return _Any()

    class _UserError(Exception):
        pass

    class _VM:
        UserError = _UserError
        class Return: pass

    class _GL:
        vm = _VM()
        class Contract: pass
        def __getattr__(self, n): return _Any()

    gl = _GL()
    gl.evm = _Any()
    gl.evm.contract_interface = lambda c: c
    gl.public = _Any()

    class _T:
        def __init__(self, *a, **k): pass
        def __class_getitem__(cls, item): return cls

    stub.gl = gl
    stub.allow_storage = lambda c: c
    stub.Address = str
    stub.DynArray = _T
    stub.TreeMap = _T
    stub.u256 = int
    stub.u32 = int
    stub.u64 = int
    stub.i64 = int
    stub.__all__ = ["gl", "allow_storage", "Address", "DynArray", "TreeMap",
                    "u256", "u32", "u64", "i64"]
    sys.modules["genlayer"] = stub

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "contracts"))
import codify as cd  # noqa: E402

import pytest  # noqa: E402


class TestBinding:
    """A stored policy must have nothing left for a later input to expose.

    This is the property the previous design lacked, and it is the reason for
    everything else in this file.
    """

    def test_two_policies_that_agree_on_samples_still_differ_canonically(self):
        """The exact failure the old design could not see.

        Both of these accept every subject up to 280 characters *in the samples
        anyone would try*, and they are not the same rule. Under finite probe
        equivalence they would have been recorded as agreeing; canonically they
        plainly do not.
        """
        a = cd._normalise({"op": "max_chars", "n": 280})
        b = cd._normalise({"op": "max_chars", "n": 281})
        samples = ["", "x" * 10, "x" * 200, "x" * 280]
        assert all(cd._apply(a, s) == cd._apply(b, s) for s in samples)
        assert cd._canon([a]) != cd._canon([b])

    def test_the_one_subject_that_tells_them_apart(self):
        a = cd._normalise({"op": "max_chars", "n": 280})
        b = cd._normalise({"op": "max_chars", "n": 281})
        assert cd._apply(a, "x" * 281) != cd._apply(b, "x" * 281)

    def test_canonical_form_pins_every_argument(self):
        base = {"op": "max_count", "of": "#", "n": 2, "ci": True}
        for field, value in (("of", "@"), ("n", 3), ("ci", False)):
            other = dict(base)
            other[field] = value
            assert cd._canon([cd._normalise(base)]) != cd._canon([cd._normalise(other)]), field

    def test_the_same_policy_written_differently_is_the_same_policy(self):
        """Two validators who listed the same strings in another order agree.

        Sorting the list is what lets an honest disagreement about ordering stop
        being a disagreement, without loosening anything about meaning.
        """
        one = cd._normalise({"op": "forbid", "any": ["https://", "http://"], "ci": True})
        two = cd._normalise({"op": "forbid", "any": ["http://", "https://"], "ci": True})
        assert cd._canon([one]) == cd._canon([two])

    def test_a_duplicate_entry_does_not_change_the_policy(self):
        one = cd._normalise({"op": "forbid", "any": ["http://", "http://"], "ci": True})
        two = cd._normalise({"op": "forbid", "any": ["http://"], "ci": True})
        assert cd._canon([one]) == cd._canon([two])

    def test_order_of_rules_is_part_of_the_policy(self):
        a = cd._normalise({"op": "max_chars", "n": 10})
        b = cd._normalise({"op": "min_chars", "n": 2})
        assert cd._canon([a, b]) != cd._canon([b, a])


class TestCatalogueIsClosed:
    """Nothing outside the table can ever be stored."""

    def test_an_unknown_predicate_is_refused(self):
        with pytest.raises(Exception) as e:
            cd._normalise({"op": "run_python", "code": "1"})
        assert cd.ERROR_MODEL in str(e.value)

    def test_an_argument_the_predicate_does_not_take_is_refused(self):
        """Silently dropping it would be a difference two validators cannot see."""
        with pytest.raises(Exception) as e:
            cd._normalise({"op": "max_chars", "n": 10, "sneaky": "value"})
        assert "does not take" in str(e.value)

    def test_a_missing_argument_is_refused(self):
        with pytest.raises(Exception):
            cd._normalise({"op": "max_chars"})
        with pytest.raises(Exception):
            cd._normalise({"op": "starts_with"})

    def test_a_non_numeric_number_is_refused(self):
        with pytest.raises(Exception):
            cd._normalise({"op": "max_chars", "n": "many"})

    def test_an_out_of_range_number_is_refused(self):
        with pytest.raises(Exception):
            cd._normalise({"op": "max_chars", "n": cd._MAX_N + 1})
        with pytest.raises(Exception):
            cd._normalise({"op": "max_chars", "n": -1})

    def test_an_overlong_string_is_refused(self):
        with pytest.raises(Exception):
            cd._normalise({"op": "starts_with", "s": "x" * (cd._MAX_NEEDLE + 1)})

    def test_an_empty_string_argument_is_refused(self):
        with pytest.raises(Exception):
            cd._normalise({"op": "starts_with", "s": ""})

    def test_an_empty_or_huge_list_is_refused(self):
        with pytest.raises(Exception):
            cd._normalise({"op": "forbid", "any": []})
        with pytest.raises(Exception):
            cd._normalise({"op": "forbid", "any": ["a" + str(i) for i in range(cd._MAX_LIST + 1)]})

    def test_a_list_where_a_string_belongs_is_refused(self):
        with pytest.raises(Exception):
            cd._normalise({"op": "forbid", "any": "http://"})

    def test_every_catalogue_entry_has_an_implementation(self):
        for op in cd._CATALOGUE:
            spec = cd._CATALOGUE[op]
            rule = {"op": op}
            for key in spec["ints"]:
                rule[key] = 1
            for key in spec["texts"]:
                rule[key] = "x"
            for key in spec["lists"]:
                rule[key] = ["x"]
            assert isinstance(cd._apply(cd._normalise(rule), "x sample 1"), bool), op


class TestPredicates:
    def n(self, **kw):
        return cd._normalise(kw)

    def test_lengths(self):
        assert cd._apply(self.n(op="max_chars", n=5), "abc")
        assert not cd._apply(self.n(op="max_chars", n=2), "abc")
        assert cd._apply(self.n(op="min_chars", n=3), "abc")
        assert not cd._apply(self.n(op="min_chars", n=4), "abc")

    def test_words_and_lines(self):
        assert cd._apply(self.n(op="max_words", n=3), "one two three")
        assert not cd._apply(self.n(op="max_words", n=2), "one two three")
        assert cd._apply(self.n(op="min_words", n=2), "one two")
        assert cd._apply(self.n(op="max_lines", n=2), "a\nb")
        assert not cd._apply(self.n(op="max_lines", n=1), "a\nb")

    def test_forbid_is_case_insensitive_by_default(self):
        rule = self.n(op="forbid", any=["http://"])
        assert rule["ci"] is True
        assert not cd._apply(rule, "see HTTP://x.com")
        assert cd._apply(rule, "nothing here")

    def test_forbid_can_be_made_exact(self):
        rule = self.n(op="forbid", any=["http://"], ci=False)
        assert cd._apply(rule, "see HTTP://x.com")

    def test_require_all_and_any(self):
        every = self.n(op="require_all", all=["signed", "off"])
        assert cd._apply(every, "signed and off")
        assert not cd._apply(every, "signed only")
        some = self.n(op="require_any", any=["fix", "feat"])
        assert cd._apply(some, "feat: something")
        assert not cd._apply(some, "chore: something")

    def test_counting(self):
        assert cd._apply(self.n(op="max_count", of="#", n=2), "#a #b")
        assert not cd._apply(self.n(op="max_count", of="#", n=2), "#a #b #c")
        assert cd._apply(self.n(op="min_count", of="@", n=1), "hi @you")

    def test_edges(self):
        assert cd._apply(self.n(op="starts_with", s="RFC:"), "rfc: hello")      # ci defaults on
        assert not cd._apply(self.n(op="starts_with", s="RFC:", ci=False), "rfc: hello")
        assert cd._apply(self.n(op="ends_with", s="."), "a sentence.")

    def test_digits(self):
        assert cd._apply(self.n(op="no_digits"), "no numbers here")
        assert not cd._apply(self.n(op="no_digits"), "room 101")
        assert cd._apply(self.n(op="has_digit"), "room 101")

    def test_the_empty_subject(self):
        """Nothing should raise on it, whatever the answer is."""
        for op in cd._CATALOGUE:
            spec = cd._CATALOGUE[op]
            rule = {"op": op}
            for key in spec["ints"]:
                rule[key] = 1
            for key in spec["texts"]:
                rule[key] = "x"
            for key in spec["lists"]:
                rule[key] = ["x"]
            assert isinstance(cd._apply(cd._normalise(rule), ""), bool), op


class TestVerdicts:
    def test_string_of_letters(self):
        policy = [cd._normalise({"op": "max_chars", "n": 10}),
                  cd._normalise({"op": "no_digits"})]
        assert cd._verdicts(policy, "abc") == "TT"
        assert cd._verdicts(policy, "abc123") == "TF"
        assert cd._verdicts(policy, "a very long subject 123") == "FF"


class TestReadRules:
    def test_plain(self):
        got = cd._read_rules({"rules": [{"op": "max_chars", "n": 280}]}, 1)
        assert got == [{"op": "max_chars", "n": 280}]

    @pytest.mark.parametrize("key", ["predicates", "policy", "checks"])
    def test_accepts_the_names_models_reach_for(self, key):
        assert cd._read_rules({key: [{"op": "no_digits"}]}, 1) == [{"op": "no_digits"}]

    def test_digs_json_out_of_chatter(self):
        raw = 'Sure:\n{"rules": [{"op": "max_chars", "n": 10}]}\nhope that helps'
        assert cd._read_rules(raw, 1)[0]["n"] == 10

    def test_refuses_the_wrong_count(self):
        with pytest.raises(Exception) as e:
            cd._read_rules({"rules": [{"op": "no_digits"}]}, 2)
        assert cd.ERROR_MODEL in str(e.value)

    def test_refuses_a_non_object(self):
        with pytest.raises(Exception):
            cd._read_rules("no json at all", 1)


class TestRequire:
    def test_carries_the_class_and_the_reason(self):
        with pytest.raises(Exception) as e:
            cd._require(False, "a rule set named x already exists")
        assert cd.ERROR_EXPECTED in str(e.value)
        assert "already exists" in str(e.value)


class TestARealRuleSet:
    """A plausible moderation policy, end to end over the deterministic half."""

    POLICY = [
        {"op": "max_chars", "n": 280},
        {"op": "forbid", "any": ["http://", "https://"], "ci": True},
        {"op": "max_count", "of": "#", "n": 2, "ci": True},
    ]
    EXAMPLES = [
        {"text": "a normal post with #one #two", "ok": True},
        {"text": "spam http://x.example", "ok": False},
        {"text": "#a #b #c #d", "ok": False},
    ]

    def test_it_agrees_with_its_examples(self):
        policy = [cd._normalise(r) for r in self.POLICY]
        got = "".join("T" if all(cd._apply(r, e["text"]) for r in policy) else "F"
                      for e in self.EXAMPLES)
        want = "".join("T" if e["ok"] else "F" for e in self.EXAMPLES)
        assert got == want

    def test_the_canonical_form_is_stable_and_reloadable(self):
        policy = [cd._normalise(r) for r in self.POLICY]
        text = cd._canon(policy)
        assert text == cd._canon(policy)
        assert [json.loads(l) for l in text.split("\n")] == policy
