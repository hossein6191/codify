# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""Codify: write the rule in English once, enforce it in code forever.

A model is asked to turn plain-language rules into Python expressions. The
expressions are run, on chain and deterministically, against examples the author
supplied — and if they disagree with the author about a single example, the
whole rule set is refused. What is stored is the code, in the open, so anyone
subject to a rule can read exactly what they are subject to.

After that the model is never called again. `check` is arithmetic: free,
instant, and identical for everybody who ever runs it.

The point is the inversion. Most contracts that use a model put it in the way of
every decision, so every decision carries its cost and its uncertainty. This one
pays for the model once, to be rid of it.
"""

import datetime
import json
from dataclasses import dataclass

from genlayer import *

# Error classes, so a validator can tell a rule of this contract from a model
# having a bad day. The first must match exactly; the second is not something to
# agree about, because agreeing would record an answer nobody produced.
ERROR_EXPECTED = "[EXPECTED]"
ERROR_MODEL = "[MODEL]"

_MAX_NAME = 48
_MAX_SOURCE = 1000       # characters of English
_MAX_RULES = 8
_MAX_EXPR = 240          # characters of Python, per rule
_MAX_EXAMPLES = 8
_MAX_SUBJECT = 2000      # characters of text a rule may be applied to

# The only names an expression may use. Everything else - imports, attributes on
# builtins, dunder anything - is absent rather than forbidden, so an expression
# that reaches for them raises NameError inside the sandbox and reads as a
# broken rule rather than as an escape. Measured on chain: `__import__('os')`
# comes back as NameError, which is the failure mode this wants.
_SAFE = {
    "len": len, "any": any, "all": all, "sum": sum, "min": min, "max": max,
    "abs": abs, "str": str, "int": int, "float": float, "bool": bool,
    "sorted": sorted, "set": set, "list": list, "enumerate": enumerate,
}
_ALLOWED = tuple(sorted(_SAFE.keys()))

# `range` is deliberately absent. Every other name here iterates over `text`,
# which is capped, so the work an expression can do is bounded by its subject.
# `range` is the one that lets a single short expression ask for an unbounded
# amount of it.
#
# And a restricted `eval` is not a sandbox. Measured: with builtins cut down to
# the list above, `().__class__.__bases__[0].__subclasses__()` still reaches 516
# classes, `Popen` and `BuiltinImporter` among them. The names were removed; the
# route through an object's type was not, because it never goes through a name.
# So expressions are refused outright if they contain a double underscore, which
# is what every version of that escape needs and no honest rule about a piece of
# text has ever wanted.
#
# The sandbox does not bound the work either. Measured: `spawn_sandbox` ran
# `sum(1 for _ in range(50_000_000))` to completion in 63 seconds and allocated
# a 300 MB string without complaint. It isolates state; it does not stop an
# expression from taking as long as it likes. So the bound has to be here.
# Without `range`, iteration is over `text`, which is capped. Without `**` and
# without long numeric literals, a repetition cannot ask for more than a subject
# times 9999.
_FORBIDDEN = ("__", "lambda", "import", ":=", ";", "**")
_MAX_LITERAL_DIGITS = 4   # 9999, comfortably past a subject capped at 2000


def _require(condition: bool, message: str) -> None:
    """Refuse with a reason the caller can read.

    A failed `assert` reaches the explorer as `exit_code 1` with the reason
    gone, which tells somebody whose rule set was refused nothing at all.
    """
    if not condition:
        raise gl.vm.UserError(ERROR_EXPECTED + " " + message)


def _lines(text: str) -> list:
    out = []
    for raw in text.split("\n"):
        line = raw.strip()
        if line:
            out.append(line)
    return out


def _env(subject: str) -> dict:
    """The whole world an expression gets to see.

    A fresh dict every call, so nothing an expression does can outlive it or
    reach the next subject.
    """
    return {"__builtins__": dict(_SAFE), "text": subject}


def _run_one(expr: str, subject: str) -> str:
    """One expression against one subject: "T", "F", or "E".

    An expression that raises is an "E" rather than a False. The difference
    matters: a rule that cannot run is broken, and a broken rule must not be
    allowed to quietly pass everything it is shown.
    """
    try:
        return "T" if bool(eval(expr, _env(subject))) else "F"
    except Exception:
        return "E"


def _behaviour(exprs: list, subjects: list) -> str:
    """How a whole rule set behaves across a whole list of subjects.

    Flattened to one string on purpose. This is what validators compare, and a
    string of T, F and E is the smallest thing that still says everything about
    what a rule set does.
    """
    out = []
    for subject in subjects:
        for expr in exprs:
            out.append(_run_one(expr, subject))
    return "".join(out)


def _probe_subjects(examples: list) -> list:
    """The author's examples, plus edge cases the author did not choose.

    An expression can satisfy every example it was shown and still be wrong,
    because the model saw those examples while it was writing. These mutations
    are generated by code from the examples themselves, so nobody — not the
    author, not the model — picked them, and an expression that only works on
    what it was shown falls apart here.
    """
    subjects = []
    for example in examples:
        subjects.append(example["text"])
    if examples:
        first = examples[0]["text"]
        subjects.append("")
        subjects.append(first[:max(1, len(first) // 2)])
        subjects.append(first + " " + first)
        subjects.append(first.upper())
    return subjects


def _read_exprs(raw, wanted: int) -> list:
    """Pull the expressions out of whatever the model returned."""
    data = raw if isinstance(raw, dict) else None
    if data is None:
        text = str(raw).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and start < end:
            try:
                candidate = json.loads(text[start:end + 1])
                if isinstance(candidate, dict):
                    data = candidate
            except Exception:
                data = None
    if not isinstance(data, dict):
        raise gl.vm.UserError(ERROR_MODEL + " the model did not return an object")
    raw_list = None
    for key in ("expressions", "exprs", "rules", "checks"):
        if key in data and isinstance(data[key], list):
            raw_list = data[key]
            break
    if raw_list is None:
        raise gl.vm.UserError(ERROR_MODEL + " the model returned no expression list")
    exprs = []
    for item in raw_list:
        if isinstance(item, dict):
            value = None
            for key in ("expression", "expr", "code", "python"):
                if key in item and item[key] is not None:
                    value = item[key]
                    break
            item = value
        if item is None:
            raise gl.vm.UserError(ERROR_MODEL + " one rule came back without an expression")
        expr = str(item).strip()
        if expr.startswith("`"):
            expr = expr.strip("`").strip()
        if len(expr) == 0 or len(expr) > _MAX_EXPR:
            raise gl.vm.UserError(ERROR_MODEL + " an expression was empty or longer than "
                                  + str(_MAX_EXPR) + " characters")
        if "\n" in expr:
            raise gl.vm.UserError(ERROR_MODEL + " an expression spanned more than one line")
        for banned in _FORBIDDEN:
            if banned in expr:
                raise gl.vm.UserError(ERROR_MODEL + " an expression contained '" + banned
                                      + "', which is refused: " + expr[:60])
        run = 0
        for ch in expr:
            run = run + 1 if ch.isdigit() else 0
            if run > _MAX_LITERAL_DIGITS:
                raise gl.vm.UserError(ERROR_MODEL + " an expression used a number longer than "
                                      + str(_MAX_LITERAL_DIGITS) + " digits: " + expr[:60])
        exprs.append(expr)
    if len(exprs) != wanted:
        raise gl.vm.UserError(ERROR_MODEL + " the model returned " + str(len(exprs))
                              + " expressions for " + str(wanted) + " rules")
    return exprs


@allow_storage
@dataclass
class RuleSet:
    name: str
    author: Address
    source: str         # the English, as written
    exprs: str          # the Python, one expression per line
    examples: str       # the JSON the author supplied
    behaviour: str      # what the accepted expressions did on the probe subjects
    at: u64


class Codify(gl.Contract):
    """Named rule sets, compiled once and enforced by code thereafter."""

    sets: DynArray[RuleSet]
    by_name: TreeMap[str, u32]

    def __init__(self) -> None:
        pass

    # ---------- helpers ----------

    def _find(self, name: str) -> int:
        _require(name in self.by_name, "no rule set named " + name)
        return int(self.by_name[name])

    # ---------- writes ----------

    @gl.public.write
    def propose(self, name: str, source: str, examples_json: str) -> str:
        """Compile English rules into expressions, and keep them only if they hold.

        The examples are the specification. A rule set that disagrees with its
        author about one of them is refused outright, because the alternative is
        storing code that nobody has checked against anything.
        """
        _require(1 <= len(name) <= _MAX_NAME, "the name must be 1 to " + str(_MAX_NAME) + " characters")
        _require(name not in self.by_name, "a rule set named " + name + " already exists")
        _require(len(source) <= _MAX_SOURCE, "the rules must be at most " + str(_MAX_SOURCE) + " characters")
        rules = _lines(source)
        _require(1 <= len(rules) <= _MAX_RULES, "write 1 to " + str(_MAX_RULES) + " rules, one per line")

        try:
            parsed = json.loads(examples_json)
        except Exception:
            _require(False, "the examples must be a JSON array")
            parsed = []
        _require(isinstance(parsed, list), "the examples must be a JSON array")
        _require(2 <= len(parsed) <= _MAX_EXAMPLES,
                 "give 2 to " + str(_MAX_EXAMPLES) + " examples")

        examples = []
        passing = 0
        failing = 0
        for item in parsed:
            _require(isinstance(item, dict) and "text" in item and "ok" in item,
                     "every example needs a text and an ok")
            subject = str(item["text"])
            _require(len(subject) <= _MAX_SUBJECT,
                     "an example is longer than " + str(_MAX_SUBJECT) + " characters")
            expected = bool(item["ok"])
            examples.append({"text": subject, "ok": expected})
            if expected:
                passing = passing + 1
            else:
                failing = failing + 1
        # A rule set that has never been shown something it should reject has
        # not been specified, only described.
        _require(passing >= 1 and failing >= 1,
                 "give at least one example that should pass and one that should fail")

        subjects = _probe_subjects(examples)
        wanted = len(rules)
        listing = "\n".join(str(i) + ". " + rules[i] for i in range(wanted))
        allowed = ", ".join(_ALLOWED)

        def leader_fn():
            def compile_rules():
                prompt = (
                    "Turn each rule into ONE Python expression that evaluates to True when the "
                    "rule is satisfied.\n\n"
                    "RULES:\n" + listing + "\n\n"
                    "The subject is a string in a variable named `text`. You may use only these "
                    "builtins: " + allowed + ". No imports, no statements, no assignments, no "
                    "lambdas, no comprehensions over anything but `text`. One line each, and it "
                    "must be an expression, not a function.\n\n"
                    "Return ONLY this JSON:\n"
                    "{\"expressions\": [\"<expression for rule 0>\", \"<expression for rule 1>\", ...]}"
                )
                answer = gl.nondet.exec_prompt(prompt, response_format="json")
                exprs = _read_exprs(answer, wanted)

                # Everything from here down is arithmetic, and it is the whole
                # reason this contract can be trusted: the model's work is put
                # to the examples and either survives them or does not.
                def measure():
                    return _behaviour(exprs, subjects)

                behaviour = str(gl.vm.unpack_result(gl.vm.spawn_sandbox(measure)))
                return {"exprs": "\n".join(exprs), "behaviour": behaviour}
            return compile_rules()

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                leader_msg = str(getattr(leaders_res, "message", ""))
                try:
                    leader_fn()
                    return False
                except gl.vm.UserError as err:
                    mine = str(getattr(err, "message", "") or str(err))
                    if mine.startswith(ERROR_EXPECTED):
                        return mine == leader_msg
                    return False
                except Exception:
                    return False
            try:
                mine = leader_fn()
            except Exception:
                return False
            # Not a comparison of the code. Two people writing the same rule in
            # Python will not write the same characters, and demanding that they
            # do would fail every honest validator. What has to match is what
            # the code DOES, on subjects neither the author nor the model chose.
            theirs = str(leaders_res.calldata.get("exprs", "")).split("\n")

            def cross():
                return _behaviour(theirs, subjects)

            leader_behaviour = str(gl.vm.unpack_result(gl.vm.spawn_sandbox(cross)))
            return leader_behaviour == str(mine.get("behaviour"))

        compiled = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        exprs = str(compiled.get("exprs", "")).split("\n")
        behaviour = str(compiled.get("behaviour", ""))

        # The deterministic gate. Consensus said what the code does; this says
        # whether that is what the author asked for, and it is decided here in
        # ordinary code rather than by anybody's opinion.
        def verdicts():
            out = []
            for example in examples:
                results = [_run_one(expr, example["text"]) for expr in exprs]
                out.append("T" if all(r == "T" for r in results) else "F")
            return "".join(out)

        got = str(gl.vm.unpack_result(gl.vm.spawn_sandbox(verdicts)))
        want = "".join("T" if example["ok"] else "F" for example in examples)
        if got != want:
            disagreed = [i for i in range(len(want)) if got[i] != want[i]]
            return json.dumps({
                "ok": False,
                "reason": "examples_disagree",
                "expected": want,
                "got": got,
                "on_examples": disagreed,
                "exprs": exprs,
                "detail": "the compiled rules disagree with your examples, so nothing was stored",
            })

        set_id = len(self.sets)
        self.sets.append(RuleSet(
            name=name,
            author=gl.message.sender_address,
            source=source,
            exprs="\n".join(exprs),
            examples=examples_json,
            behaviour=behaviour,
            at=u64(int(datetime.datetime.now(datetime.timezone.utc).timestamp())),
        ))
        self.by_name[name] = u32(set_id)
        return json.dumps({"ok": True, "id": set_id, "name": name, "rules": len(exprs), "exprs": exprs})

    # ---------- views ----------

    @gl.public.view
    def check(self, name: str, subject: str) -> str:
        """Apply a rule set. No model, no consensus, no cost.

        This is the method the contract exists to make possible, and it is
        ordinary code. Two people running it a year apart on the same subject
        get the same answer, and can each read why.
        """
        index = self._find(name)
        _require(len(subject) <= _MAX_SUBJECT,
                 "the subject is longer than " + str(_MAX_SUBJECT) + " characters")
        entry = self.sets[index]
        exprs = entry.exprs.split("\n")
        rules = _lines(entry.source)

        def evaluate():
            return "".join(_run_one(expr, subject) for expr in exprs)

        results = str(gl.vm.unpack_result(gl.vm.spawn_sandbox(evaluate)))
        detail = []
        for i in range(len(exprs)):
            outcome = results[i] if i < len(results) else "E"
            detail.append({
                "rule": rules[i] if i < len(rules) else "",
                "expression": exprs[i],
                "result": {"T": "pass", "F": "fail", "E": "error"}[outcome],
            })
        return json.dumps({
            "name": name,
            "passes": all(c == "T" for c in results),
            "results": results,
            "rules": detail,
        })

    @gl.public.view
    def explain(self, name: str) -> str:
        """The English, the Python it became, and the examples that vouched for it."""
        entry = self.sets[self._find(name)]
        return json.dumps({
            "name": entry.name,
            "author": entry.author.as_hex,
            "source": entry.source,
            "expressions": entry.exprs.split("\n"),
            "examples": entry.examples,
            "behaviour_on_probes": entry.behaviour,
            "at": int(entry.at),
        })

    @gl.public.view
    def count(self) -> int:
        return len(self.sets)

    @gl.public.view
    def names(self) -> str:
        return "\n".join(entry.name for entry in self.sets)

    @gl.public.view
    def vocabulary(self) -> str:
        """What an expression is allowed to name. Everything else is absent."""
        return ", ".join(_ALLOWED)
