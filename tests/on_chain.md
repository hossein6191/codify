# What was measured on chain

`tests/test_pure.py` covers the catalogue, the binding and the canonical form. It
cannot reach the question the contract exists to answer: whether five validators,
each asked to bind the same English to predicates, arrive at the same policy —
every argument of it, not a sample of what it does.

```
npm i genlayer-js viem
node tests/on_chain/smoke.mjs                17 assertions, a fresh Codify
CODIFY=0x… node tests/on_chain/gate.mjs       6 assertions, a second contract enforcing a rule set
```

## The binding

```
17 passed, 0 failed          Codify 0xe319B9f460a98899628e31cFB4F8085F54947150
```

Three rules in English, bound to three predicates:

```
votes: 3 agree, 1 disagree, 1 idle  →  applied

{"n":280,"op":"max_chars"}
{"any":["http://","https://","www."],"ci":true,"op":"forbid"}
{"ci":false,"n":2,"of":"#","op":"max_count"}
```

**Validators disagree now, and that is the point.** Across two runs of the same
three rules the tallies were 3–1 and 3–2: validators that bound a different
policy said so. The previous design could not see those disagreements, because it
compared what the programs *did* on a fixed list of subjects rather than what the
policy *was*, and two different programs will usually behave the same on any list
somebody thought of in advance.

| what | result |
|---|---|
| every predicate came from the catalogue | `max_chars`, `forbid`, `max_count` |
| a clean subject through `check` | `TTT`, no model, no consensus |
| a spammy subject | `TFF`, naming the rules and the predicates that decided |
| which predicate rejected it | `[["pass","max_chars"],["fail","forbid"],["fail","max_count"]]` |
| the canonical form | rebuildable from the stored policy |
| a rule set with no failing example | refused: *give at least one that should pass and one that should fail* |
| one example | refused: *give 2 to 8 examples* |
| a name used twice | refused: *a rule set named no-spam already exists* |
| the published catalogue | 14 predicates, closed, readable before anybody writes a rule |

**The deterministic gate fired.** Asked for *"the text must be longer than 100
characters"* with examples saying the opposite, the bound policy came back `FT`
where the author had specified `TF`. Nothing was stored, and the refusal handed
back `[{"n":101,"op":"min_chars"}]` — the exact predicate that was written for
them, and which their own examples then rejected.

## A second contract enforcing the rules

`contracts/fixtures/gate.py` is a submission box that accepts a post only when a
named rule set allows it, through
`gl.get_contract_at(...).view().check(name, subject)` — synchronous,
deterministic, no model.

```
6 passed, 0 failed           Gate 0x7E8e5920687D87dd0317078A2de59f2d5c10e515
```

That Gate run predates the redesign and read a first-design Codify. The script
now defaults to the current deployment,
`0x37c472780A4F20F12356010cba0D72686FCa6083`, whose `check` returns the same
shape: the consumer reads `passes` and the rule text, neither of which the
redesign changed.

| assertion | result |
|---|---|
| a clean post is accepted | 3 agree → `{"ok": true, "id": 0}` |
| a post breaking the rules is refused | 3 agree → `{"ok": false, "broke": ["it must not contain a URL", "it must have at most two hashtags"]}` |
| a 268-character subject | accepted — past what a `gen_call` view can carry |
| the ledger | 2 accepted, 1 refused |

The second row is what makes the contract worth deploying: the consumer is told
which rules were broken **in the author's own English**, and no validator was
asked anything about the post.

## Findings from the version that used generated code

The first design ran model-written Python inside `gl.vm.spawn_sandbox`. It was
refused on consensus grounds and replaced, but these measurements are true of
GenLayer generally and are the reason nobody should reach for that pattern
casually.

| question | probe | answer |
|---|---|---|
| does `eval` with cut-down builtins contain an expression? | local + `0x402e153B…` | **no** — `().__class__.__bases__[0].__subclasses__()` reaches 516 classes locally, 335 on chain, `Popen` among them |
| does `spawn_sandbox` bound the work? | `0x402e153B3463C5dEDb85661e6fA49a41779eC4E9` | **no** — a 50,000,000 iteration loop ran to completion in 63 s; a 300 MB string allocated fine |
| does sandboxed `eval` reach consensus at all? | `0xf78C7A61A5EF669709eC0bb796130E0dc00728E5` | yes — but agreeing on a sample of behaviour is not agreeing on a policy |
| can a GenLayer contract be called with `gl.evm.contract_interface`? | `0x45F3D7Bd…` | **no** — the deploy dies in the constructor with `exit_code 1` and the address answers *not found* |
| how long an argument can a `gen_call` view carry? | `0x94B1488a…` (a first-design deployment, kept only as the probe it was) | about 250 characters; past that, `RLP string ends with N superfluous bytes` |

The first probe of the sandbox was itself nearly misleading: its "infinite loop"
case failed with `NameError`, not a timeout, because `range` was not in that
probe's vocabulary — so it never looped, and the question went unanswered until
it was asked again properly. The second answer was the opposite of the first.

## What is not covered here

Adversarial rule text. The author writes the English and the English reaches the
model, so steering the binding through the rules themselves is a real avenue.

It is much narrower than it was. The worst a steered model can do now is pick a
catalogue predicate with arguments the author did not intend — and that policy
still has to satisfy the author's own examples, and is still published in full.
There is no code to smuggle, because there is nowhere for code to go.
