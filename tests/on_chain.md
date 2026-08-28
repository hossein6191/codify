# What was measured on chain

`tests/test_pure.py` covers the sandbox walls, the bounds and the parsing. It
cannot reach the question the contract exists to answer: whether five validators,
each asked to write Python for the same English, arrive at code that behaves the
same way.

```
npm i genlayer-js viem
node tests/on_chain/smoke.mjs     16 assertions, a fresh Codify
node tests/on_chain/gate.mjs       6 assertions, a second contract enforcing a rule set
```

## The compilation

```
16 passed, 0 failed          Codify 0xCC2e218602FF729613FebE6Ae1917ED1b9a6E73d
```

Three rules in English became three expressions, with a real dissenter:

```
votes: 3 agree, 1 disagree, 1 idle  →  applied

len(text) <= 280
all(s not in text for s in ('http://', 'https://', 'www.'))
sum(1 for c in text if c == '#') <= 2
```

**Compiled three times, the model wrote three different programs.**

```
run 1   text.find('http://') == -1 and text.find('https://') == -1 and text.find('www.') == -1
run 2   all(s not in text for s in ('http://', 'https://', 'www.'))
run 3   'http://' not in text and 'https://' not in text
```

All three are correct. No two are the same string. The third is the one deployed
from the author's wallet at `0x3Bdc3C84…`, which reached 3 agree and 0 disagree. This is the entire reason
validators compare behaviour rather than characters — a contract demanding
identical code would have rejected every honest validator in both runs and never
stored a rule at all.

| what | result |
|---|---|
| a rule set with no failing example | refused: *give at least one example that should pass and one that should fail* |
| one example | refused: *give 2 to 8 examples* |
| a name used twice | refused: *a rule set named no-spam already exists* |
| a clean subject through `check` | `TTT`, no model, no consensus |
| a spammy subject | `TFF`, naming the two rules it broke and the code that decided |
| the stored expressions | no `__`, no `lambda`, no `**` |
| the published vocabulary | `abs any all bool enumerate float int len list max min set sorted str sum` — no `range` |

**The deterministic gate fired.** Asked for *"the text must be longer than 100
characters"* with examples that said the opposite, the compiled code came back
`FT` where the author had specified `TF`. Nothing was stored, and the refusal
handed back `["len(text) > 100"]` so the author can see exactly what was written
for them and why it disagreed.

## A second contract enforcing the rules

`contracts/fixtures/gate.py` is a submission box that accepts a post only when a
named rule set allows it. It calls
`gl.get_contract_at(...).view().check(name, subject)` — synchronous,
deterministic, no model.

```
6 passed, 0 failed           Gate 0x7E8e5920687D87dd0317078A2de59f2d5c10e515
```

| assertion | result |
|---|---|
| a clean post is accepted | 3 agree → `{"ok": true, "id": 0}` |
| a post breaking the rules is refused | 3 agree → `{"ok": false, "broke": ["it must not contain a URL", "it must have at most two hashtags"]}` |
| a 268-character subject | accepted — past what a `gen_call` view can carry |
| the ledger | 2 accepted, 1 refused |

The second row is what makes the contract worth deploying. The consumer is told
which rules were broken **in the author's own English**, and no validator was
asked anything about the post.

## The probes behind the design

Each of these changed the contract.

| question | probe | answer |
|---|---|---|
| does `eval` with cut-down builtins contain an expression? | local + `0x402e153B…` | **no** — `().__class__.__bases__[0].__subclasses__()` reaches 516 classes locally, 335 on chain, `Popen` among them |
| does `spawn_sandbox` bound the work? | `0x402e153B3463C5dEDb85661e6fA49a41779eC4E9` | **no** — a 50,000,000 iteration loop ran to completion in 63 s; a 300 MB string allocated fine |
| does sandboxed `eval` reach consensus at all? | `0xf78C7A61A5EF669709eC0bb796130E0dc00728E5` | yes — 3 to 4 validators agreeing on every case |
| can a GenLayer contract be called with `gl.evm.contract_interface`? | `0x45F3D7Bd…` | **no** — the deploy dies in the constructor with `exit_code 1` and the address answers *not found* |
| how long an argument can a `gen_call` view carry? | `0x94B1488a…` | about 250 characters; past that, `RLP string ends with N superfluous bytes` |

The first two are why every bound lives in the contract rather than under it.
The first probe was also nearly misleading: its "infinite loop" case failed with
`NameError`, not a timeout, because `range` was not in that probe's vocabulary —
so it never looped, and the question went unanswered until it was asked again
properly.

## What is not covered here

Adversarial rule text. An author writes the English, and the English reaches the
model, so prompt injection aimed at making the model emit a hostile expression is
a real avenue. The syntactic refusals — `__`, `lambda`, `import`, `:=`, `;`,
`**`, long numeric literals — are the defence, and they are checked in
`test_pure.py` against every escape the author of this contract could think of.
That last clause is the honest limit of it.
