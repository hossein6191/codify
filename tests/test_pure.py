"""The half of Codify that never asks anybody anything.

Everything here runs the way it runs on chain: the same sandbox environment, the
same T/F/E encoding, the same probe generation. What these cannot reach is
whether validators agree on a compilation, which is what tests/on_chain.md is
for.

The tests that matter most are the ones about what an expression is *not*
allowed to reach, because that is the boundary between a rule engine and a hole.
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


class TestRunOne:
    """T, F or E — and the difference between the last two is the whole point."""

    def test_true(self):
        assert cd._run_one("len(text) <= 10", "short") == "T"

    def test_false(self):
        assert cd._run_one("len(text) <= 3", "much longer") == "F"

    def test_a_broken_expression_is_an_error_not_a_pass(self):
        """A rule that cannot run must never read as satisfied.

        If a broken expression came back False it would look like an ordinary
        rejection; if it came back True it would wave everything through. It
        gets its own letter so neither can happen quietly.
        """
        assert cd._run_one("len(text ==", "x") == "E"
        assert cd._run_one("undefined_name > 1", "x") == "E"
        assert cd._run_one("text.no_such_method()", "x") == "E"

    def test_truthiness_is_forced_to_a_bool(self):
        assert cd._run_one("text", "non-empty") == "T"
        assert cd._run_one("text", "") == "F"
        assert cd._run_one("len(text)", "abc") == "T"


class TestSandboxWalls:
    """What an expression cannot reach.

    Nothing here is forbidden by a blocklist — the names simply are not present,
    so reaching for one is a NameError. A blocklist is a list of the escapes
    somebody thought of.
    """

    @pytest.mark.parametrize("hostile", [
        "__import__('os').listdir('/')",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "exec('x=1')",
        "globals()",
        "locals()",
        "vars()",
        "getattr(text, 'upper')()",
        "type(text)",
        "dir(text)",
        "compile('1','x','eval')",
        "input()",
        "print(text)",
    ])
    def test_is_not_reachable(self, hostile):
        assert cd._run_one(hostile, "x") == "E"

    def test_the_dunder_route_is_refused_before_it_ever_runs(self):
        """`().__class__.__bases__` is the classic way out of a bare eval, and it
        works: with builtins cut to the allowed list it still reaches 516
        classes, Popen among them. Names were removed; the route through an
        object's type never went through a name.

        So it is stopped a step earlier, when the expression is read.
        """
        escape = "().__class__.__bases__[0].__subclasses__()"
        assert cd._run_one(escape, "x") in ("T", "F")   # eval alone does not stop it
        with pytest.raises(Exception) as e:
            cd._read_exprs({"expressions": [escape]}, 1)
        assert "__" in str(e.value)

    @pytest.mark.parametrize("banned", [
        "().__class__", "lambda x: x", "import os", "(y := 1)", "1; 2",
    ])
    def test_the_forbidden_shapes_are_refused(self, banned):
        with pytest.raises(Exception):
            cd._read_exprs({"expressions": ["len(text) > 0 and " + banned]}, 1)

    def test_range_is_not_in_the_vocabulary(self):
        """Everything else iterates over `text`, which is capped."""
        assert "range" not in cd._ALLOWED
        assert cd._run_one("sum(1 for _ in range(1000))", "x") == "E"

    @pytest.mark.parametrize("greedy", [
        "len(text*100000000) > 0",
        "len(text*10**8) > 0",
        "len(str(99999999999)) > 0",
    ])
    def test_an_expression_cannot_ask_for_unbounded_work(self, greedy):
        """The sandbox will not stop it, so this has to.

        Measured on chain: spawn_sandbox ran a fifty million iteration loop to
        completion and allocated a 300 MB string. It isolates state, not effort.
        """
        with pytest.raises(Exception):
            cd._read_exprs({"expressions": [greedy]}, 1)

    def test_ordinary_numbers_still_pass(self):
        for expr in ("len(text) <= 280", "text.count('#') <= 2", "len(text) > 9999"):
            assert cd._read_exprs({"expressions": [expr]}, 1) == [expr]

    def test_the_allowed_names_do_work(self):
        for expr in ("len(text) > 0", "any(c.isdigit() for c in text)",
                     "all(c != '@' for c in text)", "max(1, len(text)) > 0",
                     "sum(1 for c in text if c == 'a') < 5",
                     "sorted(set(text)) == sorted(set(text))"):
            assert cd._run_one(expr, "abc123") in ("T", "F"), expr

    def test_the_environment_holds_only_what_it_says(self):
        env = cd._env("x")
        assert set(env.keys()) == {"__builtins__", "text"}
        assert set(env["__builtins__"].keys()) == set(cd._ALLOWED)

    def test_one_subject_cannot_leak_into_another(self):
        """A fresh environment each time, so no expression can plant anything."""
        cd._run_one("text", "first")
        assert cd._env("second")["text"] == "second"


class TestBehaviour:
    def test_is_expression_major_within_each_subject(self):
        exprs = ["len(text) > 0", "len(text) > 5"]
        assert cd._behaviour(exprs, ["abc", "abcdefg"]) == "TF" + "TT"

    def test_empty_inputs(self):
        assert cd._behaviour([], ["a"]) == ""
        assert cd._behaviour(["len(text)>0"], []) == ""

    def test_carries_errors_through(self):
        assert cd._behaviour(["len(text ==", "len(text) > 0"], ["a"]) == "ET"


class TestProbeSubjects:
    """The examples, plus mutations nobody chose.

    A model writing an expression can see the examples. It cannot see these, and
    an expression that only works on what it was shown comes apart here.
    """

    EXAMPLES = [{"text": "hello world", "ok": True}, {"text": "no", "ok": False}]

    def test_keeps_every_example(self):
        subjects = cd._probe_subjects(self.EXAMPLES)
        assert "hello world" in subjects
        assert "no" in subjects

    def test_adds_the_edges(self):
        subjects = cd._probe_subjects(self.EXAMPLES)
        assert "" in subjects
        assert "HELLO WORLD" in subjects
        assert "hello world hello world" in subjects

    def test_a_length_rule_overfitted_to_the_examples_is_exposed(self):
        """Both rules agree on the examples; only the probes tell them apart."""
        honest = "len(text) <= 11"
        overfit = "text in ('hello world', 'no')"
        examples = [e["text"] for e in self.EXAMPLES]
        assert cd._behaviour([honest], examples) == cd._behaviour([overfit], examples)
        probes = cd._probe_subjects(self.EXAMPLES)
        assert cd._behaviour([honest], probes) != cd._behaviour([overfit], probes)

    def test_no_examples_means_no_probes(self):
        assert cd._probe_subjects([]) == []


class TestReadExprs:
    def test_plain(self):
        got = cd._read_exprs({"expressions": ["len(text) < 10", "'@' in text"]}, 2)
        assert got == ["len(text) < 10", "'@' in text"]

    @pytest.mark.parametrize("key", ["exprs", "rules", "checks"])
    def test_accepts_the_names_models_reach_for(self, key):
        assert cd._read_exprs({key: ["len(text) < 10"]}, 1) == ["len(text) < 10"]

    def test_accepts_objects_instead_of_strings(self):
        got = cd._read_exprs({"expressions": [{"rule": "short", "expression": "len(text) < 10"}]}, 1)
        assert got == ["len(text) < 10"]

    def test_strips_a_code_fence(self):
        assert cd._read_exprs({"expressions": ["`len(text) < 10`"]}, 1) == ["len(text) < 10"]

    def test_digs_json_out_of_chatter(self):
        raw = 'Here you go:\n{"expressions": ["len(text) < 10"]}\nHope that helps!'
        assert cd._read_exprs(raw, 1) == ["len(text) < 10"]

    def test_refuses_the_wrong_count(self):
        with pytest.raises(Exception) as e:
            cd._read_exprs({"expressions": ["len(text) < 10"]}, 2)
        assert cd.ERROR_MODEL in str(e.value)

    def test_refuses_a_multi_line_expression(self):
        with pytest.raises(Exception):
            cd._read_exprs({"expressions": ["x = 1\nlen(text)"]}, 1)

    def test_refuses_an_overlong_expression(self):
        with pytest.raises(Exception):
            cd._read_exprs({"expressions": ["x" * (cd._MAX_EXPR + 1)]}, 1)

    def test_refuses_an_empty_expression(self):
        with pytest.raises(Exception):
            cd._read_exprs({"expressions": ["   "]}, 1)

    def test_refuses_a_non_object(self):
        with pytest.raises(Exception):
            cd._read_exprs("no json here at all", 1)


class TestLines:
    def test_drops_blanks_and_trims(self):
        assert cd._lines("  a  \n\n  b\n \n c ") == ["a", "b", "c"]

    def test_empty(self):
        assert cd._lines("") == []
        assert cd._lines("\n\n  \n") == []


class TestRequire:
    def test_carries_the_class_and_the_reason(self):
        with pytest.raises(Exception) as e:
            cd._require(False, "a rule set named x already exists")
        assert cd.ERROR_EXPECTED in str(e.value)
        assert "already exists" in str(e.value)


class TestARealRuleSet:
    """End to end over the deterministic half: a plausible moderation policy."""

    EXPRS = ["len(text) <= 280", "'http' not in text", "text.count('#') <= 2"]
    EXAMPLES = [
        {"text": "a normal post #one #two", "ok": True},
        {"text": "spam http://x.com", "ok": False},
        {"text": "#a #b #c #d", "ok": False},
    ]

    def test_the_examples_come_out_as_the_author_said(self):
        got = "".join(
            "T" if all(cd._run_one(e, ex["text"]) == "T" for e in self.EXPRS) else "F"
            for ex in self.EXAMPLES)
        want = "".join("T" if ex["ok"] else "F" for ex in self.EXAMPLES)
        assert got == want

    def test_behaviour_is_stable_across_runs(self):
        probes = cd._probe_subjects(self.EXAMPLES)
        assert cd._behaviour(self.EXPRS, probes) == cd._behaviour(self.EXPRS, probes)

    def test_a_differently_written_but_equivalent_rule_set_matches(self):
        """What validators compare is behaviour, not characters.

        Two people writing the same policy in Python do not write the same
        string, and a contract that demanded they did would reject every honest
        validator it ever had.
        """
        other = ["not len(text) > 280", "text.find('http') == -1",
                 "len([c for c in text if c == '#']) < 3"]
        probes = cd._probe_subjects(self.EXAMPLES)
        assert cd._behaviour(other, probes) == cd._behaviour(self.EXPRS, probes)
