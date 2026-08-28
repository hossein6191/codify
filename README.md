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

## Verified on the Studio network

Deployed from the author's own wallet `0x0A9fd8Fe0b041974e8F794fCf3Eed352c14cf5fe`
against `studio.genlayer.com`. The deployed bytecode is byte-identical to
`contracts/codify.py` in this repo (sha256
`9f6caa6f39b25bd8210f317e63d4ce462885b4d4c0f05887d91b4edc49367b6f`), and the code
pulled back off the chain passes `genvm-lint check` — pull it out of the deploy
transaction and hash it yourself.

Contract [`0x3Bdc3C84…`](https://explorer-studio.genlayer.com/address/0x3Bdc3C840f646caE6B63eE470d2947FfDC92a697)
([deploy ↗](https://explorer-studio.genlayer.com/tx/0x25aac7a26e11d086c8f5c9c503fa9f766d8b519f9e5b8851ab14e129207d9a12))

**Rule set `no-spam`.** Three rules in English, compiled once.
[propose ↗](https://explorer-studio.genlayer.com/tx/0x3db6be9bb3b0a918eaf91f69e79ec8157e115ad0657ca52c842db718d3c57cfb)
— 3 agree, 0 disagree, 2 idle.

| the rule, as written | the Python it became |
|---|---|
| the text must be at most 280 characters | `len(text) <= 280` |
| it must not contain a URL | `'http://' not in text and 'https://' not in text` |
| it must have at most two hashtags | `text.count('#') <= 2` |

Then, with no model involved at all:

```
check("no-spam", "an ordinary sentence with #one tag")   → passes, TTT
check("no-spam", "buy now http://x.example #a #b #c")    → fails,  TFF
```

Read it back with `explain("no-spam")` or run `check` yourself. It costs nothing
and it will answer the same thing forever.

**The same three rules have now been compiled three times, and produced three
different programs.**

```
run 1   text.find('http://') == -1 and text.find('https://') == -1 and text.find('www.') == -1
run 2   all(s not in text for s in ('http://', 'https://', 'www.'))
run 3   'http://' not in text and 'https://' not in text
```

All three are correct. No two are the same string. This is the whole argument for
comparing behaviour rather than characters, and it is not a hypothetical — a
contract that demanded identical code would have failed every one of these runs
and never stored a rule at all.

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

MIT licensed. Take the sandbox walls, the behaviour comparison, or the whole
thing.
