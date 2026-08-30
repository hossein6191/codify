# Decisions, and what was measured rather than assumed

Everything below was checked on the GenLayer Studio network or against the code
as it runs. Where something is untested it says so.

## The redesign, and the review that caused it

The first version of this contract asked the model for arbitrary Python, one
expression per rule, and had validators agree when the leader's expressions and
their own produced the same results on the author's examples plus some mutations
generated from them. It was submitted, and refused:

> The contract has a thoughtful compile-once design, but the validator only
> compares generated expressions on a finite set of examples and mutations. A
> leader expression can match every tested subject while behaving differently on
> a later input, and that stored expression controls future checks and downstream
> contract decisions. Please redesign consensus so validators independently bind
> the full consequential policy rather than accepting finite probe equivalence.

That is correct, and it is worth being precise about why, because the old design
looked careful.

Two programs can agree on every subject anyone thought to try and part company on
the next one. The mutations helped — they caught expressions overfitted to the
examples — but they only widened the sample. They did not close it. And the thing
that got stored was the **leader's** program: every later `check`, and every
contract reading `check`, would obey a program the validators had approved a
sample of the behaviour of. They had ratified an extrapolation.

Adding more probes could not fix it. There is no finite set of subjects whose
agreement implies agreement everywhere, so the fix had to remove the gap rather
than narrow it.

## What replaced it: a closed catalogue

The model no longer writes code. It chooses, for each English rule, one predicate
from a fixed table and fills in its arguments:

```json
{"op": "max_chars", "n": 280}
{"op": "forbid", "any": ["http://", "https://"], "ci": true}
{"op": "max_count", "of": "#", "n": 2, "ci": true}
```

Validators then compare the **whole policy** in canonical form — every predicate
and every argument — as an exact string. Not a sample of what it does. There is
no later input on which the stored policy can differ from what each validator
approved, because each validator approved all of it.

`{"op":"max_chars","n":280}` and `{"op":"max_chars","n":281}` agree on every
subject anybody would naturally test and are plainly different policies. The
pure tests pin exactly that case, because it is the shape of the bug the old
design could not see.

### What canonicalisation settles, and what it must not

| difference | treated as |
|---|---|
| `["https://","http://"]` vs `["http://","https://"]` | the same policy — lists are sorted |
| a repeated entry in a list | the same policy — duplicates are dropped |
| `{"n":280}` vs `{"n":281}` | different policies |
| rule order | different policies; the order is the author's |
| an argument the predicate does not take | **refused**, not ignored |

That last row matters more than it looks. A field quietly dropped is a
difference between two validators that neither of them can see, which is the
same failure the review described, arriving by a different door.

## Measured: validators really do disagree now

On chain, binding three English rules with the redesigned contract:

```
votes: 3 agree, 2 disagree, 0 idle  →  applied

{"n":280,"op":"max_chars"}
{"any":["http://","https://","www."],"ci":true,"op":"forbid"}
{"ci":false,"n":2,"of":"#","op":"max_count"}
```

Two validators bound a *different* policy and said so. Under the old design the
same two might well have been recorded as agreeing, because their programs would
have behaved identically on the probe subjects. The disagreement is not a
failure — it is the mechanism working, and it is visible now where before it was
invisible.

## What removing `eval` also removed

The old version ran model-written code inside `gl.vm.spawn_sandbox`. That is gone
with it, and so are three problems measured while trying to make it safe. They
are recorded here because they are true of GenLayer generally, and anybody
reaching for the same pattern should know them.

**A restricted `eval` is not a sandbox.** With `__builtins__` cut down to a safe
list, `().__class__.__bases__[0].__subclasses__()` still reached **516 classes**
locally and **335 on chain** — `Popen`, `BuiltinImporter`, `FileLoader` among
them. The escape never goes through a name, so removing names does not close it.

**`spawn_sandbox` isolates state, not work.** Measured on probe
`0x402e153B3463C5dEDb85661e6fA49a41779eC4E9`:
`sum(1 for _ in range(50000000))` ran to completion in 63 seconds, and
`len(text * 100000000)` allocated a 300 MB string. Nothing was cut short. Any
contract that runs supplied code must bound it itself; there is no backstop
underneath.

**A probe can answer the wrong question.** The first sandbox probe reported that
an infinite loop was stopped. It was not — the loop died of `NameError` because
`range` was not in that probe's vocabulary, so it never looped at all. The
question went unanswered until it was asked again properly, and the second
answer was the opposite of the first.

None of these can bite this contract any more, because it executes its own
predicates in ordinary Python and there is no supplied code anywhere.

## The examples are the specification

`propose` refuses a rule set unless it comes with at least one example that
should pass **and** one that should fail. A rule set never shown something it
ought to reject has not been specified, only described.

After consensus fixes the policy, the policy is run against those examples in
ordinary code. If it disagrees with the author about one of them, nothing is
stored and the bound predicates are handed back so the author can see what was
written for them and where it diverged. The model's work is checked by execution
rather than by another model.

## Errors are refusals, not results

Refusals raise `gl.vm.UserError`. A failed `assert` reaches the explorer as
`exit_code 1` with the reason thrown away, which tells somebody whose rule set
was refused nothing at all.

The one place a refusal is *returned* rather than raised — the policy
disagreeing with the examples — is deliberate: nothing has been written at that
point, and the caller needs the policy back to see what went wrong.

## Calling this contract from another one

`@gl.evm.contract_interface` describes an **EVM** contract. Pointing it at a
GenLayer contract lints, validates, and then dies in the constructor with
`exit_code 1`, after which the address answers `Contract ... not found`. The
pattern that works:

```python
raw = gl.get_contract_at(self.other).view().check(name, subject)
```

`contracts/fixtures/gate.py` is a working consumer built on it.

## A view call over RPC cannot carry a long argument

Measured against a deployed Codify, calling `check(name, subject)`:

| subject | result |
|---|---|
| up to 200 characters | fine |
| 300 characters | `RLP string ends with 333 superfluous bytes` |
| 1000 characters | `RLP string ends with 1033 superfluous bytes` |

The count of "superfluous" bytes tracks the argument, so the whole payload is
rejected somewhere past about 250 characters. It is specific to `gen_call`: a
**write** carrying ~1900 characters was processed normally, a view *returning*
586 characters was fine, and a 268-character subject passed through
`gl.get_contract_at(...).view().check(...)` without trouble.

`_MAX_SUBJECT` stays at 2000 because that is what the contract can take. Anyone
reading it straight from a browser will hit a wall of the node's own first.

## What is still not covered

Adversarial rule text. The author writes the English and the English reaches the
model, so an attempt to steer the binding through the rules themselves is a real
avenue.

It is a much smaller avenue than it was. The worst a steered model can now do is
choose a predicate from the catalogue with arguments the author did not intend —
and that policy still has to satisfy the author's own examples, and is still
published in full for anyone to read. There is no code to smuggle, because there
is nowhere for code to go.
