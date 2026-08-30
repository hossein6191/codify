# Codify

**Write the rule in English once. Enforce it in code forever.**

A model reads plain-language rules and binds each one to a predicate from a
closed catalogue. Validators compare the whole resulting policy, exactly. Then
the policy is run against the author's own examples, and if it disagrees with
them about a single one, nothing is stored.

After that the model is never called again.

```
propose("no-spam",
        "the text must be at most 280 characters
         it must not contain a URL
         it must have at most two hashtags",
        examples)

  → each validator binds the rules to predicates
  → they agree only if they bound the same policy, argument for argument
  → the policy is run against your examples, in ordinary code
  → it disagrees with one? nothing is stored, and you get the policy back
  → it holds? the predicates are kept, in public

check("no-spam", subject)   ← no model, no consensus, no cost. Forever.
explain("no-spam")          ← the English, and the predicates it became
```

## The inversion

Most contracts that use a model put it in the way of every decision, so every
decision carries its latency, its cost, and the chance that five validators do
not agree.

This one pays for the model once, in order to be rid of it. Consensus is reached
on a *binding* — something that happens a single time — and every enforcement
afterwards is arithmetic that anyone can rerun and nobody can dispute.

It also makes the rule auditable in a way an ongoing model call never is. If a
model decides your post breaks a policy, there is nothing to inspect. If
`{"op":"max_count","of":"#","n":2}` decides it, you can read the rule you broke.

## What validators agree on

The whole policy, canonically, exactly — every predicate and every argument of
the thing that will be stored and obeyed.

That is not how this contract started. The first version had the model write
Python and had validators agree when the leader's expressions and their own gave
the same answers on the author's examples plus some generated mutations. A
reviewer refused it, correctly:

> A leader expression can match every tested subject while behaving differently
> on a later input, and that stored expression controls future checks and
> downstream contract decisions.

Two programs can agree on every subject anyone thought to try and differ on the
next one. More probes only widen the sample; they never close it. So the fix was
to remove the gap rather than narrow it — with a closed catalogue,
`{"op":"max_chars","n":280}` has exactly one meaning, and two validators either
bound the same policy or they did not.

Measured on chain after the redesign: binding three rules gave **3 agree, 2
disagree**. Two validators bound a different policy and said so. Under the old
design those two might well have been counted as agreeing, because their
programs would have behaved identically on every probe.

## The catalogue

The complete vocabulary of every policy this contract can ever enforce, readable
with `catalogue()` before anybody writes a rule:

```
max_chars(n)      min_chars(n)      max_words(n)     min_words(n)
max_lines(n)      no_digits()       has_digit()
forbid(any, ci)   require_all(all, ci)   require_any(any, ci)
max_count(of, n, ci)   min_count(of, n, ci)
starts_with(s, ci)     ends_with(s, ci)
```

The cost is expressiveness: a rule the catalogue cannot express is refused
rather than approximated. For a contract whose output governs money and access,
refusing what it cannot represent is the right failure.

There is no `eval` anywhere, and no sandbox. The contract runs its own
predicates.

## What it is for

- **Moderation policies** a community writes in its own words and can then point
  at, argument by argument, when it enforces them.
- **Submission requirements** — a grant form, a bounty, a competition entry —
  where the same check has to be applied identically to everybody.
- **Any contract that needs a gate**: `check` is a view, so another contract can
  read it with `gl.get_contract_at(addr).view().check(name, subject)` and pay
  nothing for consensus. `contracts/fixtures/gate.py` is a working example — a
  submission box that accepts a post only when a named rule set allows it, and
  tells the author which of their own rules it broke.

One caveat before you build on it: an RPC `gen_call` view cannot carry a string
argument much past 250 characters — the node answers `RLP string ends with N
superfluous bytes`. That limit is the RPC path's, not the contract's. Writes
carry far more, and contract-to-contract calls are unaffected.

## The examples are the specification

`propose` refuses a rule set unless it comes with at least one example that
should pass **and** one that should fail. A rule set that has never been shown
something it ought to turn away has not been specified, only described.

After consensus fixes the policy, the policy is run against those examples in
ordinary code. If it disagrees with the author about one of them the proposal is
refused, and the bound predicates are handed back so the author can see what was
written for them and where it diverged.

## Reading a result

`check` returns what happened, rule by rule, with the predicate that decided it:

```json
{
  "name": "no-spam",
  "passes": false,
  "results": "TFT",
  "rules": [
    {"rule": "at most 280 characters", "predicate": {"n": 280, "op": "max_chars"}, "result": "pass"},
    {"rule": "must not contain a URL", "predicate": {"any": ["http://"], "ci": true, "op": "forbid"}, "result": "fail"},
    {"rule": "at most two hashtags", "predicate": {"n": 2, "of": "#", "op": "max_count"}, "result": "pass"}
  ]
}
```

## Tests

```
tests/test_pure.py        36 tests, no chain: the catalogue, the binding, the canonical form
tests/on_chain/smoke.mjs  the binding itself, against real validators
tests/on_chain/gate.mjs   a second contract enforcing a rule set through it
```

`tests/on_chain.md` records the vote tallies, because a transaction can finalise
with a split vote and apply nothing — the status alone never says a rule set was
stored.

`DECISIONS.md` records what was measured, including three findings about running
model-written code on GenLayer that no longer bite this contract but will bite
anyone who tries the same thing.

---

MIT licensed. Take the catalogue, the canonical binding, or the whole thing.
