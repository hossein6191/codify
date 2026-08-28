# Codify

**Write the rule in English once. Enforce it in code forever.**

A model turns plain-language rules into Python expressions. The expressions are
run on chain, deterministically, against examples the author supplied — and if
they disagree with the author about a single example, nothing is stored. What is
kept is the code, in the open, so anyone subject to a rule can read exactly what
they are subject to.

After that the model is never called again.

```
propose("no-spam",
        "the text must be at most 280 characters
         it must not contain a URL
         it must have at most two hashtags",
        examples)

  → the validators each write Python for it
  → the code is run against the examples, in ordinary arithmetic
  → it disagrees with one? nothing is stored, and you get the code back
  → it holds? the expressions are kept, in public

check("no-spam", subject)   ← no model, no consensus, no cost. Forever.
explain("no-spam")          ← the English, and the Python it became
```

## The inversion

Most contracts that use a model put it in the way of every decision, so every
decision carries its latency, its cost, and the chance that five validators do
not agree.

This one pays for the model once, in order to be rid of it. Consensus is reached
on a *compilation* — a thing that happens a single time — and every enforcement
afterwards is arithmetic that anyone can rerun and nobody can dispute.

That also makes the rule auditable in a way an ongoing model call never is. If a
model decides your post breaks a policy, there is nothing to inspect. If
`text.count("#") <= 2` decides it, you can read the rule you broke.

## What it is for

- **Moderation policies** a community writes in its own words and can then point
  at, character by character, when it enforces them.
- **Submission requirements** — a grant form, a bounty, a competition entry —
  where the same check has to be applied identically to everybody.
- **Any contract that needs a gate**: `check` is a view, so another contract can
  read it with `gl.get_contract_at(addr).view().check(name, subject)` and pay
  nothing for consensus. `contracts/fixtures/gate.py` is a working example — a
  submission box that accepts a post only when a named rule set allows it, and
  tells the author which of their own rules it broke.

One caveat worth knowing before you build on it: an RPC `gen_call` view cannot
carry a string argument much past 250 characters — the node answers `RLP string
ends with N superfluous bytes`. That limit is the RPC path's, not the
contract's. Writes carry far more, and contract-to-contract calls are unaffected.

## How a proposal is judged

Three things happen, and only the first involves a model.

**One — compilation.** Each validator is shown the rules and asked for one
Python expression per rule, over a variable named `text`.

**Two — agreement, by execution.** Two people writing the same rule do not write
the same characters:

```python
text.count("#") <= 2
len([c for c in text if c == "#"]) < 3
not text.count("#") > 2
```

Comparing strings would reject every honest validator. So the leader's
expressions and the validator's own are both *run*, over the same subjects, and
the validator agrees when the two produce identical results. Code is compared by
what it does.

The subjects are the author's examples **plus** mutations generated from them by
code — the empty string, a half, a doubling, an uppercasing. An expression can
satisfy every example it was shown and still be wrong, because the model could
see those examples while it was writing. It cannot see these.

**Three — the deterministic gate.** After consensus, the agreed code is run
against the examples in ordinary Python. If it disagrees with the author about
one of them, the proposal is refused and the code is handed back so they can see
why. Nothing is stored.

The examples are the specification, which is why at least one of them has to be
something the rules should **reject**. A rule set that has never been shown
something it ought to turn away has not been specified, only described.

## What an expression may contain

```
len any all sum min max abs str int float bool sorted set list enumerate
```

and the subject, `text`. Everything else is absent rather than forbidden, so
reaching for it is a `NameError`.

Refused outright, before the expression ever runs: `__`, `lambda`, `import`,
`:=`, `;`, `**`, and any number longer than four digits.

Those are not decoration. A restricted `eval` is not a sandbox — with builtins
cut to the list above, `().__class__.__bases__[0].__subclasses__()` still reaches
516 classes, `Popen` among them, because the escape never goes through a name.
And `spawn_sandbox` will not save you: measured on chain, it ran a fifty-million
iteration loop to completion and allocated a 300 MB string without complaint. It
isolates state, not effort.

So the bounds are here, in the contract. `range` is absent because it is the one
name that lets a short expression ask for unbounded work; everything left
iterates over a subject that is capped. `DECISIONS.md` has the measurements.

## Reading a result

`check` returns what happened, rule by rule, with the code that decided it:

```json
{
  "name": "no-spam",
  "passes": false,
  "results": "TFT",
  "rules": [
    {"rule": "at most 280 characters", "expression": "len(text) <= 280", "result": "pass"},
    {"rule": "must not contain a URL", "expression": "'http' not in text", "result": "fail"},
    {"rule": "at most two hashtags", "expression": "text.count('#') <= 2", "result": "pass"}
  ]
}
```

`T`, `F`, `E` — and the third is not a kind of failure. An expression that
raises is a *broken* rule, not a rejected subject, and it says so. Returning
`False` for a broken rule would look like an ordinary rejection; returning `True`
would wave everything through.

## Tests

```
tests/test_pure.py        56 tests, no chain: the walls, the bounds, the parsing
tests/on_chain/smoke.mjs  16 assertions, the compilation against real validators
tests/on_chain/gate.mjs    6 assertions, a second contract enforcing a rule set
```

`tests/on_chain.md` records the vote tallies, because a transaction can finalise
with a split vote and apply nothing — the status alone never says a rule set was
stored.

---

Built by **Hellish** · [x.com/Hellishnum1](https://x.com/Hellishnum1) · [github.com/hossein6191](https://github.com/hossein6191)

MIT licensed. Take the sandbox walls, the behaviour comparison, or the whole
thing.
