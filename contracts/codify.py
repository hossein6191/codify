# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""Codify: write the rule in English once, enforce it in code forever.

A model reads plain-language rules and chooses, for each one, a predicate from a
closed catalogue and the arguments to fill it. Validators compare the resulting
policy in canonical form, exactly. Then the policy is run against the author's
own examples, and if it disagrees with them about a single one, nothing is
stored.

After that the model is never called again. `check` walks the stored predicates
in ordinary code: free, deterministic, and identical for everybody who ever runs
it.

Why a catalogue rather than generated code
------------------------------------------
An earlier version of this contract asked the model for arbitrary Python and had
validators agree when the leader's expressions and their own produced the same
results on the author's examples plus some generated mutations. That is finite
probe equivalence, and it does not bind. Two expressions can agree on every
subject anyone thought to try and part company on the next one — and it was the
*leader's* expression that got stored and that every later `check`, and every
downstream contract reading it, would obey. The validators had approved a sample
of a program's behaviour and inherited all of it.

A closed catalogue removes the gap instead of narrowing it. `{"op":"max_chars",
"n":280}` has exactly one meaning, so two validators either chose the same
policy or they did not, and comparing them is string equality over a canonical
form rather than a guess about the future. There is no input, ever, on which the
stored policy can surprise the validators who approved it.

It also means no `eval`, no sandbox and no generated code anywhere: the contract
executes the predicates itself.

The cost is expressiveness. Only rules the catalogue can express can be written,
and one it cannot is refused outright. For a contract whose output governs money
and access, refusing what it cannot represent is the right failure.
"""

import datetime
import json
from dataclasses import dataclass

from genlayer import *

# Error classes, so a validator can tell a rule of this contract from a model
# having a bad day. The first must match exactly; the second is not something to
# agree about, because agreeing would record a policy nobody produced.
ERROR_EXPECTED = "[EXPECTED]"
ERROR_MODEL = "[MODEL]"

_MAX_NAME = 48
_MAX_SOURCE = 1000        # characters of English
_MAX_RULES = 8
_MAX_EXAMPLES = 8
_MAX_SUBJECT = 2000       # characters of text a rule may be applied to
_MAX_NEEDLE = 80          # characters in any string argument
_MAX_LIST = 8             # entries in a list argument
_MAX_N = 100000           # the largest number any predicate will accept

# The catalogue. Each entry names the arguments a predicate takes, and nothing
# outside this table can ever be stored. A reader can hold the entire vocabulary
# of every policy this contract will ever enforce in their head.
#
#   ints    the integer arguments, required
#   texts   the single-string arguments, required
#   lists   the string-list arguments, required
#   ci      whether the predicate accepts a case-insensitive flag
_CATALOGUE = {
    "max_chars":   {"ints": ("n",), "texts": (), "lists": (), "ci": False},
    "min_chars":   {"ints": ("n",), "texts": (), "lists": (), "ci": False},
    "max_words":   {"ints": ("n",), "texts": (), "lists": (), "ci": False},
    "min_words":   {"ints": ("n",), "texts": (), "lists": (), "ci": False},
    "max_lines":   {"ints": ("n",), "texts": (), "lists": (), "ci": False},
    "forbid":      {"ints": (), "texts": (), "lists": ("any",), "ci": True},
    "require_all": {"ints": (), "texts": (), "lists": ("all",), "ci": True},
    "require_any": {"ints": (), "texts": (), "lists": ("any",), "ci": True},
    "max_count":   {"ints": ("n",), "texts": ("of",), "lists": (), "ci": True},
    "min_count":   {"ints": ("n",), "texts": ("of",), "lists": (), "ci": True},
    "starts_with": {"ints": (), "texts": ("s",), "lists": (), "ci": True},
    "ends_with":   {"ints": (), "texts": ("s",), "lists": (), "ci": True},
    "no_digits":   {"ints": (), "texts": (), "lists": (), "ci": False},
    "has_digit":   {"ints": (), "texts": (), "lists": (), "ci": False},
}


def _require(condition: bool, message: str) -> None:
    """Refuse with a reason the caller can read.

    A failed `assert` reaches the explorer as `exit_code 1` with the reason
    thrown away, which tells somebody whose rule set was refused nothing at all.
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


def _normalise(rule) -> dict:
    """Turn one thing the model returned into a catalogue entry, or refuse it.

    Strict on purpose. Every field is checked against the catalogue and anything
    unrecognised is an error rather than something silently dropped, because a
    field that is quietly ignored is a difference between two validators that
    neither of them can see.
    """
    if not isinstance(rule, dict):
        raise gl.vm.UserError(ERROR_MODEL + " a rule came back as something other than an object")
    op = str(rule.get("op", "")).strip().lower()
    if op not in _CATALOGUE:
        raise gl.vm.UserError(ERROR_MODEL + " unknown predicate '" + op[:30]
                              + "'; the catalogue is " + ", ".join(sorted(_CATALOGUE.keys())))
    spec = _CATALOGUE[op]
    out = {"op": op}

    for key in spec["ints"]:
        if key not in rule:
            raise gl.vm.UserError(ERROR_MODEL + " " + op + " needs '" + key + "'")
        try:
            value = int(str(rule[key]).strip())
        except Exception:
            raise gl.vm.UserError(ERROR_MODEL + " " + op + "'s '" + key + "' is not a whole number")
        if not 0 <= value <= _MAX_N:
            raise gl.vm.UserError(ERROR_MODEL + " " + op + "'s '" + key + "' is out of range")
        out[key] = value

    for key in spec["texts"]:
        if key not in rule:
            raise gl.vm.UserError(ERROR_MODEL + " " + op + " needs '" + key + "'")
        value = str(rule[key])
        if not 1 <= len(value) <= _MAX_NEEDLE:
            raise gl.vm.UserError(ERROR_MODEL + " " + op + "'s '" + key + "' must be 1 to "
                                  + str(_MAX_NEEDLE) + " characters")
        out[key] = value

    for key in spec["lists"]:
        if key not in rule or not isinstance(rule[key], list):
            raise gl.vm.UserError(ERROR_MODEL + " " + op + " needs '" + key + "' as a list")
        items = []
        for item in rule[key]:
            value = str(item)
            if not 1 <= len(value) <= _MAX_NEEDLE:
                raise gl.vm.UserError(ERROR_MODEL + " an entry in " + op + "'s '" + key
                                      + "' must be 1 to " + str(_MAX_NEEDLE) + " characters")
            if value not in items:
                items.append(value)
        if not 1 <= len(items) <= _MAX_LIST:
            raise gl.vm.UserError(ERROR_MODEL + " " + op + "'s '" + key + "' must hold 1 to "
                                  + str(_MAX_LIST) + " entries")
        # Sorted, so two validators that listed the same strings in a different
        # order have written the same policy and are recorded as agreeing.
        items.sort()
        out[key] = items

    if spec["ci"]:
        out["ci"] = bool(rule.get("ci", True))

    known = set(out.keys())
    for key in rule:
        if str(key) not in known:
            raise gl.vm.UserError(ERROR_MODEL + " " + op + " was given an argument it does not take: "
                                  + str(key)[:24])
    return out


def _canon(rules: list) -> str:
    """The whole policy, in one form, with nothing left to interpretation.

    This is what validators compare. Not a sample of what the policy does — the
    policy itself, every argument of it, in an order that cannot vary.
    """
    return "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rules)


def _apply(rule: dict, subject: str) -> bool:
    """One predicate against one subject. Ordinary code, no eval anywhere."""
    op = rule["op"]
    fold = rule.get("ci", False)
    hay = subject.lower() if fold else subject

    if op == "max_chars":
        return len(subject) <= rule["n"]
    if op == "min_chars":
        return len(subject) >= rule["n"]
    if op == "max_words":
        return len(subject.split()) <= rule["n"]
    if op == "min_words":
        return len(subject.split()) >= rule["n"]
    if op == "max_lines":
        return len(subject.split("\n")) <= rule["n"]
    if op == "no_digits":
        for ch in subject:
            if ch.isdigit():
                return False
        return True
    if op == "has_digit":
        for ch in subject:
            if ch.isdigit():
                return True
        return False
    if op == "starts_with":
        needle = rule["s"].lower() if fold else rule["s"]
        return hay.startswith(needle)
    if op == "ends_with":
        needle = rule["s"].lower() if fold else rule["s"]
        return hay.endswith(needle)
    if op == "max_count":
        needle = rule["of"].lower() if fold else rule["of"]
        return hay.count(needle) <= rule["n"]
    if op == "min_count":
        needle = rule["of"].lower() if fold else rule["of"]
        return hay.count(needle) >= rule["n"]
    if op == "forbid":
        for item in rule["any"]:
            if (item.lower() if fold else item) in hay:
                return False
        return True
    if op == "require_all":
        for item in rule["all"]:
            if (item.lower() if fold else item) not in hay:
                return False
        return True
    if op == "require_any":
        for item in rule["any"]:
            if (item.lower() if fold else item) in hay:
                return True
        return False
    # Unreachable: _normalise refuses anything not in the catalogue, and the
    # catalogue and this function are the two halves of the same table.
    raise gl.vm.UserError(ERROR_EXPECTED + " no implementation for predicate " + op)


def _verdicts(rules: list, subject: str) -> str:
    return "".join("T" if _apply(r, subject) else "F" for r in rules)


def _read_rules(raw, wanted: int) -> list:
    """Pull the policy out of whatever the model returned, and bind every field."""
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
    listed = None
    for key in ("rules", "predicates", "policy", "checks"):
        if key in data and isinstance(data[key], list):
            listed = data[key]
            break
    if listed is None:
        raise gl.vm.UserError(ERROR_MODEL + " the model returned no rule list")
    if len(listed) != wanted:
        raise gl.vm.UserError(ERROR_MODEL + " the model returned " + str(len(listed))
                              + " predicates for " + str(wanted) + " rules")
    return [_normalise(item) for item in listed]


@allow_storage
@dataclass
class RuleSet:
    name: str
    author: Address
    source: str         # the English, as written
    policy: str         # the canonical predicates, one JSON object per line
    examples: str       # the JSON the author supplied
    at: u64


class Codify(gl.Contract):
    """Named rule sets, bound once and enforced by code thereafter."""

    sets: DynArray[RuleSet]
    by_name: TreeMap[str, u32]

    def __init__(self) -> None:
        pass

    # ---------- helpers ----------

    def _find(self, name: str) -> int:
        _require(name in self.by_name, "no rule set named " + name)
        return int(self.by_name[name])

    def _policy(self, index: int) -> list:
        return [json.loads(line) for line in self.sets[index].policy.split("\n") if line]

    # ---------- writes ----------

    @gl.public.write
    def propose(self, name: str, source: str, examples_json: str) -> str:
        """Bind English rules to predicates, and keep them only if they hold.

        The examples are the specification. A policy that disagrees with its
        author about one of them is refused outright, because the alternative is
        storing a rule nobody has checked against anything.
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
        _require(2 <= len(parsed) <= _MAX_EXAMPLES, "give 2 to " + str(_MAX_EXAMPLES) + " examples")

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
        # A rule set that has never been shown something it should reject has not
        # been specified, only described.
        _require(passing >= 1 and failing >= 1,
                 "give at least one example that should pass and one that should fail")

        wanted = len(rules)
        listing = "\n".join(str(i) + ". " + rules[i] for i in range(wanted))
        catalogue = json.dumps({
            "max_chars": {"n": "int"}, "min_chars": {"n": "int"},
            "max_words": {"n": "int"}, "min_words": {"n": "int"},
            "max_lines": {"n": "int"},
            "forbid": {"any": ["string"], "ci": "bool"},
            "require_all": {"all": ["string"], "ci": "bool"},
            "require_any": {"any": ["string"], "ci": "bool"},
            "max_count": {"of": "string", "n": "int", "ci": "bool"},
            "min_count": {"of": "string", "n": "int", "ci": "bool"},
            "starts_with": {"s": "string", "ci": "bool"},
            "ends_with": {"s": "string", "ci": "bool"},
            "no_digits": {}, "has_digit": {},
        }, sort_keys=True)

        def leader_fn():
            def bind():
                prompt = (
                    "Bind each rule to exactly one predicate from this catalogue, filling in its "
                    "arguments. The subject the predicate is applied to is a piece of text.\n\n"
                    "CATALOGUE (predicate: its arguments):\n" + catalogue + "\n\n"
                    "RULES:\n" + listing + "\n\n"
                    "Return one predicate per rule, in the same order. Use no predicate that is "
                    "not in the catalogue and no argument a predicate does not take. If a rule "
                    "cannot be expressed with exactly one of these, return it anyway using the "
                    "closest predicate — a wrong binding will be caught by the author's examples "
                    "and refused, which is better than an invented one.\n\n"
                    "Return ONLY this JSON:\n"
                    "{\"rules\": [{\"op\": \"...\", ...}, ...]}"
                )
                answer = gl.nondet.exec_prompt(prompt, response_format="json")
                return {"policy": _canon(_read_rules(answer, wanted))}
            return bind()

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
            # The whole policy, canonically, exactly. Not a sample of what it
            # does on subjects somebody thought of — every predicate and every
            # argument of the thing that will be stored and obeyed. There is no
            # later input on which the stored policy can differ from what this
            # validator approved, because this validator approved all of it.
            return str(mine.get("policy")) == str(leaders_res.calldata.get("policy"))

        bound = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        policy_text = str(bound.get("policy", ""))
        policy = [json.loads(line) for line in policy_text.split("\n") if line]

        # The deterministic gate. Consensus fixed the policy; this decides
        # whether it is the one the author asked for, in ordinary code.
        got = "".join("T" if all(_apply(r, e["text"]) for r in policy) else "F" for e in examples)
        want = "".join("T" if e["ok"] else "F" for e in examples)
        if got != want:
            disagreed = [i for i in range(len(want)) if got[i] != want[i]]
            return json.dumps({
                "ok": False,
                "reason": "examples_disagree",
                "expected": want,
                "got": got,
                "on_examples": disagreed,
                "policy": policy,
                "detail": "the bound predicates disagree with your examples, so nothing was stored",
            })

        set_id = len(self.sets)
        self.sets.append(RuleSet(
            name=name,
            author=gl.message.sender_address,
            source=source,
            policy=policy_text,
            examples=examples_json,
            at=u64(int(datetime.datetime.now(datetime.timezone.utc).timestamp())),
        ))
        self.by_name[name] = u32(set_id)
        return json.dumps({"ok": True, "id": set_id, "name": name,
                           "rules": len(policy), "policy": policy})

    # ---------- views ----------

    @gl.public.view
    def check(self, name: str, subject: str) -> str:
        """Apply a rule set. No model, no consensus, no cost, no eval.

        The contract walks its own predicates. Two people running this a year
        apart on the same subject get the same answer, and can each read why.
        """
        index = self._find(name)
        _require(len(subject) <= _MAX_SUBJECT,
                 "the subject is longer than " + str(_MAX_SUBJECT) + " characters")
        policy = self._policy(index)
        rules = _lines(self.sets[index].source)
        results = _verdicts(policy, subject)
        detail = []
        for i in range(len(policy)):
            detail.append({
                "rule": rules[i] if i < len(rules) else "",
                "predicate": policy[i],
                "result": "pass" if results[i] == "T" else "fail",
            })
        return json.dumps({
            "name": name,
            "passes": all(c == "T" for c in results),
            "results": results,
            "rules": detail,
        })

    @gl.public.view
    def explain(self, name: str) -> str:
        """The English, the predicates it bound to, and the examples that vouched."""
        index = self._find(name)
        entry = self.sets[index]
        return json.dumps({
            "name": entry.name,
            "author": entry.author.as_hex,
            "source": entry.source,
            "policy": self._policy(index),
            "canonical": entry.policy,
            "examples": entry.examples,
            "at": int(entry.at),
        })

    @gl.public.view
    def count(self) -> int:
        return len(self.sets)

    @gl.public.view
    def names(self) -> str:
        return "\n".join(entry.name for entry in self.sets)

    @gl.public.view
    def catalogue(self) -> str:
        """Every predicate this contract will ever enforce.

        The complete vocabulary of every policy that can be stored here, so a
        reader can see the outer edge of what they might be subjected to before
        anybody writes a rule.
        """
        out = []
        for op in sorted(_CATALOGUE.keys()):
            spec = _CATALOGUE[op]
            args = list(spec["ints"]) + list(spec["texts"]) + list(spec["lists"])
            if spec["ci"]:
                args.append("ci")
            out.append(op + "(" + ", ".join(args) + ")")
        return "\n".join(out)
