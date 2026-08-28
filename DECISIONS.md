# Decisions, and what was measured rather than assumed

Everything below was checked on the GenLayer Studio network or against the code
as it runs. Where something is untested it says so.

## `spawn_sandbox` isolates state. It does not bound work.

This is the most important thing in this file, the name says the opposite, and
getting it wrong would have shipped a contract that any author could stall.

Measured on probe `0x402e153B3463C5dEDb85661e6fA49a41779eC4E9`, expressions
evaluated inside `gl.vm.spawn_sandbox`:

| expression | result |
|---|---|
| `sum(1 for _ in range(1000))` | SUCCESS, 39 s |
| `sum(1 for _ in range(50000000))` | **SUCCESS, 63 s** |
| `len(text * 100000000)` | **SUCCESS** — a 300 MB string, allocated and measured |
| `len(().__class__.__bases__[0].__subclasses__())` | **SUCCESS — 335 classes reachable** |

Nothing was cut short. Fifty million iterations ran to completion; a three
hundred megabyte allocation succeeded. The sandbox keeps an expression from
touching contract state, which is what it is for, and it will happily let one
take as long as it likes doing nothing.

So every bound in this contract is in this contract. There is no backstop
underneath it.

## A restricted `eval` is not a sandbox

Removing names from `__builtins__` looks like it shuts the door. It does not,
because the classic escape never uses a name:

```python
().__class__.__bases__[0].__subclasses__()
```

Locally that reaches **516 classes** with builtins cut to the allowed list —
`Popen`, `BuiltinImporter`, `FileLoader`, `_wrap_close` among them. On chain,
inside `spawn_sandbox`, it reaches 335. An attribute lookup on a tuple gets to
`object`, and `object` knows every subclass in the process.

Blocklists of *names* are therefore beside the point. What is refused instead is
the shape: an expression containing `__` never runs at all. Every version of
that escape needs a dunder, and no honest rule about a piece of text has ever
wanted one. `lambda`, `import`, `:=` and `;` go the same way, for the same
reason: a rule is an expression, and none of those belong in one.

## The bounds, and why each one is there

| refused | because |
|---|---|
| `__` | the escape above; every form of it needs a dunder |
| `lambda`, `:=`, `;` | a rule is one expression; these are how it stops being one |
| `import` | there is nothing to import and nothing that should be |
| `**` | the compact way to write a number large enough to hurt |
| any run of 5+ digits | the other way; a subject caps at 2000, so 9999 is generous |
| `range` (absent, not banned) | every remaining name iterates over `text`, which is capped |

`range` is the only name in a plausible vocabulary that lets one short
expression ask for unbounded work, so it is simply not there. What is left can
loop over the subject and no further.

Together these mean the worst an expression can do is walk a 2000 character
string a few thousand times. That is a bound, not a hope.

## Validators compare behaviour, not code

Two people asked to write Python for *"at most two hashtags"* will not write the
same characters:

```python
text.count("#") <= 2
len([c for c in text if c == "#"]) < 3
not text.count("#") > 2
```

All three are the same rule. A contract that compared the strings would reject
every honest validator it ever had, and one that asked a model whether two
snippets are equivalent would be back to trusting a model about the thing it was
supposed to check.

So the comparison is by execution. The leader's expressions and the validator's
own are both run over the same list of subjects, and the validator agrees when
the two produce an identical string of `T`, `F` and `E`. Code is compared by
what it does, which is the only property anyone actually cares about.

## Errors are a third outcome, not a kind of false

`_run_one` returns `T`, `F` or `E`. An expression that raises is not a rule that
failed — it is a rule that is broken, and the two must not be confused.

Returning `False` for a broken rule would make it look like an ordinary
rejection; returning `True` would wave everything through. The third letter
means a broken rule is visible in `check`, visible in the stored behaviour
string, and visible to a validator comparing behaviour, so it cannot pass
quietly in either direction.

## The examples are the specification

`propose` refuses a rule set unless it comes with at least one example that
should pass **and** one that should fail.

A rule set that has never been shown something it ought to reject has not been
specified, only described. And the pair is what makes the deterministic gate
possible: after consensus produces the code, the code is run against the
examples in ordinary Python, and if it disagrees with the author about a single
one, nothing is stored. The model's work is checked by execution rather than by
another model.

## The probes the author did not choose

An expression can satisfy every example it was shown and still be wrong, because
the model could see those examples while it was writing.

So the subjects used for validator comparison are the examples **plus**
mutations generated from them by code: the empty string, the first half of the
first example, that example doubled, and it uppercased. Nobody picked them — not
the author, not the model — and an expression that only works on what it was
shown comes apart on them.

The pure tests demonstrate the case: `len(text) <= 11` and
`text in ('hello world', 'no')` agree on every example and disagree on the
probes.

## Calling another GenLayer contract is not `gl.evm.contract_interface`

The two look interchangeable and one of them does not work.

`@gl.evm.contract_interface` describes an **EVM** contract. Pointing it at a
GenLayer contract compiles, lints, and passes validation — and then the deploy
dies in the constructor with `exit_code 1`, which says nothing about why. Three
subsequent calls to the address answer `Contract ... not found`, because nothing
was ever deployed there.

The pattern that works is the one `schema-oracle` already uses:

```python
raw = gl.get_contract_at(self.other).view().check(name, subject)
```

`contracts/fixtures/gate.py` is a working consumer, and the difference between
the version that failed and the version that works is those two lines.

## A view call over RPC cannot carry a long argument. Contract to contract can.

Measured against a deployed Codify, calling `check(name, subject)` with subjects
of increasing length:

| subject | result |
|---|---|
| 10, 50, 100, 200 characters | fine |
| 300 characters | `RLP string ends with 333 superfluous bytes` |
| 500 characters | `RLP string ends with 533 superfluous bytes` |
| 1000 characters | `RLP string ends with 1033 superfluous bytes` |

The number of "superfluous" bytes tracks the argument, so the whole payload is
being rejected somewhere past about 250 characters.

It is specific to `gen_call`. In the same session:

- a **write** carrying a ~1900 character payload was accepted and processed
  normally, and the model compiled `len(text) < 900` from it;
- a view **returning** 586 characters was fine;
- and a 268 character subject — comfortably past the limit — went through
  `gl.get_contract_at(...).view().check(...)` from `Gate` without trouble.

So the ceiling belongs to the RPC path, not to the contract, the network, or
composition. `_MAX_SUBJECT` stays at 2000 because that is what the contract can
actually take; anyone reading it straight from a browser over `gen_call` should
know they will hit a wall of the node's own long before that.

## Why there is no model in `check`

`check` is a view. It runs stored code, deterministically, for free, and returns
the same answer for everybody forever.

That is the whole point of the contract, and it is the opposite of the usual
shape. A contract that puts a model in front of every decision pays for it every
time, in latency, in cost, and in the chance that five validators do not agree.
Here the model is asked one question, once, in public, and what it produced is
readable by anyone the rule will ever be applied to.

## Refusals raise; they do not assert and they do not return

A failed `assert` reaches the explorer as `exit_code 1` with the reason thrown
away. `raise gl.vm.UserError(msg)` carries the text and still marks the
execution an error, which is what rolls the state back.

Returning the message instead would read the same and be wrong: the execution
succeeds, so anything written before the return is kept. The one place this
contract *does* return a refusal — compiled rules disagreeing with the examples
— is deliberate and safe, because nothing has been written at that point and the
caller needs the code back to see what went wrong.

There is no payable method here, so the trap that costs money elsewhere on this
chain — value sent with a refused payable call is not returned — does not arise.
