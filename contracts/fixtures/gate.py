# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""A consumer, to prove the point of the whole thing.

Codify is only worth building if another contract can enforce a rule set without
paying for consensus every time. This is that other contract: a submission box
that accepts a post only when a named rule set says it may.

The call is `gl.get_contract_at(...).view()`, which is synchronous and
deterministic — so `post` reaches consensus the way a transfer does, with no
model consulted and no validator asked anything about the post.

(`gl.evm.contract_interface` is for EVM contracts and fails here: a deploy using
it dies in the constructor with `exit_code 1`.)
"""

import json

from genlayer import *


class Gate(gl.Contract):
    """A box that only takes posts a rule set allows."""

    codify: Address
    rules: str
    accepted: DynArray[str]
    refused: u32

    def __init__(self, codify: str, rules: str) -> None:
        self.codify = Address(codify)
        self.rules = rules
        self.refused = u32(0)

    @gl.public.write
    def post(self, text: str) -> str:
        """Accept a post, if the rule set says so.

        The whole decision is one synchronous view call into another contract.
        It costs nothing beyond the gas of the call already being made.
        """
        raw = gl.get_contract_at(self.codify).view().check(self.rules, text)
        verdict = json.loads(raw)
        if not verdict.get("passes"):
            self.refused = u32(int(self.refused) + 1)
            broke = []
            for entry in verdict.get("rules", []):
                if entry.get("result") != "pass":
                    broke.append(entry.get("rule", ""))
            return json.dumps({"ok": False, "broke": broke})
        self.accepted.append(text)
        return json.dumps({"ok": True, "id": len(self.accepted) - 1})

    @gl.public.view
    def count(self) -> int:
        return len(self.accepted)

    @gl.public.view
    def rejections(self) -> int:
        return int(self.refused)
