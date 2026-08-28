/* Codify, against the live Studio network.
 *
 * The pure tests cover the sandbox walls and the parsing. They cannot reach the
 * one thing that decides whether this contract works at all: whether five
 * validators, each asked to write Python for the same English, end up with code
 * that behaves the same way — because none of them will write the same
 * characters, and comparing characters would fail every honest validator.
 *
 *   npm i genlayer-js viem && node tests/on_chain/smoke.mjs
 *
 * Vote tallies are read off the chain. A transaction can finalise with a split
 * vote and apply nothing, so the status alone never says a rule set was stored.
 */
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { generatePrivateKey } from "viem/accounts";
import { readFileSync } from "node:fs";

const RPC = "https://studio.genlayer.com/api";
const rpc = async (m, p) => {
  const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: m, params: p }) });
  return (await r.json()).result;
};
let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log(`${c ? "PASS" : "FAIL"}  ${n}${d ? "  — " + d : ""}`); };

const acc = createAccount(generatePrivateKey());
await rpc("sim_fundAccount", { account_address: acc.address, amount: 500e18 });
const c = createClient({ chain: studionet, account: acc });
const rd = createClient({ chain: studionet });
const code = readFileSync(new URL("../../contracts/codify.py", import.meta.url));
const h = await c.deployContract({ code, args: [], leaderOnly: false });
const A = (await c.waitForTransactionReceipt({ hash: h, status: "ACCEPTED", retries: 40, interval: 4000 }))?.data?.contract_address;
console.log("Codify at", A, "\n");

const wait = async (tx) => {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 4000));
    const t = await rpc("eth_getTransactionByHash", [tx]);
    if (t?.status === "CANCELED") return { msg: "CANCELED", exec: "CANCELED", votes: {} };
    if (t?.status === "FINALIZED") {
      const lr = t.consensus_data?.leader_receipt, one = Array.isArray(lr) ? lr[0] : lr;
      let msg = ""; try { msg = Buffer.from(one.result, "base64").toString("utf8").replace(/[^\x20-\x7e]/g, " ").trim(); } catch (e) {}
      let a = 0, d = 0, idl = 0;
      for (const k in (t.consensus_data?.votes || {})) { const v = t.consensus_data.votes[k]; if (v === "agree") a++; else if (v === "disagree") d++; else idl++; }
      return { msg, exec: one?.execution_result, votes: { a, d, idl }, applied: a * 2 > a + d + idl };
    }
  }
  return { msg: "TIMEOUT", exec: "", votes: {} };
};
const propose = async (name, source, examples) => {
  const r = await wait(await c.writeContract({ address: A, functionName: "propose",
    args: [name, source, JSON.stringify(examples)] }));
  let j = null;
  const brace = r.msg.indexOf("{");
  if (brace !== -1) { try { j = JSON.parse(r.msg.slice(brace)); } catch (e) {} }
  return { ...r, j };
};
const view = async (fn, args = []) => await rd.readContract({ address: A, functionName: fn, args });
const tally = (r) => `${r.votes.a} agree, ${r.votes.d} disagree, ${r.votes.idl} idle`;

// ---------- refusals that never reach a model ----------
const noFail = await propose("all-good", "the text must be under 280 characters",
  [{ text: "short", ok: true }, { text: "also short", ok: true }]);
ok("a rule set with nothing it should reject is refused",
   noFail.exec === "ERROR" && noFail.msg.includes("at least one example that should pass"),
   noFail.msg.slice(0, 80));

const tooFew = await propose("thin", "the text must be short", [{ text: "a", ok: true }]);
ok("one example is not a specification", tooFew.exec === "ERROR" && tooFew.msg.includes("2 to"), tooFew.msg.slice(0, 70));

// ---------- the compilation this contract exists for ----------
const policy = [
  { text: "a normal post with #one #two", ok: true },
  { text: "check this out http://spam.example", ok: false },
  { text: "#a #b #c #d #e", ok: false },
];
const moderation = await propose("no-spam",
  "the text must be at most 280 characters\nit must not contain a URL\nit must have at most two hashtags",
  policy);
ok("plain English became working Python",
   moderation.j?.ok === true, `${tally(moderation)} → ${JSON.stringify(moderation.j?.exprs)}`);
ok("one expression per rule", moderation.j?.rules === 3, String(moderation.j?.rules));

// ---------- and from here there is no model at all ----------
const clean = JSON.parse(await view("check", ["no-spam", "just an ordinary sentence"]));
ok("a clean subject passes", clean.passes === true, clean.results);
const spam = JSON.parse(await view("check", ["no-spam", "buy now http://x.example #a #b #c"]));
ok("a spammy subject fails", spam.passes === false, spam.results);
ok("and it says which rule failed and why",
   Array.isArray(spam.rules) && spam.rules.some((r) => r.result === "fail") && spam.rules.every((r) => r.expression),
   JSON.stringify(spam.rules.map((r) => [r.result, r.expression.slice(0, 30)])));

/* A gen_call view cannot carry a long string argument — the node answers
   "RLP string ends with N superfluous bytes" somewhere past 250 characters.
   That is an RPC limit, not a contract one: the same subject goes through fine
   contract-to-contract, which is what tests/on_chain/gate.mjs shows. */
const long = JSON.parse(await view("check", ["no-spam", "x".repeat(200)]));
ok("the length rule is enforced, within what a view call can carry",
   long.passes === true, long.results);

// ---------- the code is readable by whoever is subject to it ----------
const ex = JSON.parse(await view("explain", ["no-spam"]));
ok("explain returns the English and the Python side by side",
   ex.source.includes("280") && Array.isArray(ex.expressions) && ex.expressions.length === 3,
   JSON.stringify(ex.expressions));
ok("no expression smuggled in a forbidden shape",
   ex.expressions.every((e) => !e.includes("__") && !e.includes("lambda") && !e.includes("**")),
   JSON.stringify(ex.expressions));
ok("the author is recorded", ex.author.toLowerCase() === acc.address.toLowerCase());

// ---------- a rule set that cannot honour its own examples is not stored ----------
const impossible = await propose("contradiction",
  "the text must be longer than 100 characters",
  [{ text: "short", ok: true }, { text: "x".repeat(200), ok: false }]);
ok("compiled rules that disagree with the examples are refused, not stored",
   impossible.j?.ok === false && impossible.j.reason === "examples_disagree",
   `${tally(impossible)} → expected ${impossible.j?.expected} got ${impossible.j?.got}`);
ok("and the refusal shows the code it rejected",
   Array.isArray(impossible.j?.exprs) && impossible.j.exprs.length === 1, JSON.stringify(impossible.j?.exprs));
ok("nothing was written for it", Number(await view("count")) === 1, String(await view("count")));

// ---------- names are unique ----------
const dupe = await propose("no-spam", "anything at all here",
  [{ text: "a", ok: true }, { text: "b", ok: false }]);
ok("a name cannot be taken twice", dupe.exec === "ERROR" && dupe.msg.includes("already exists"), dupe.msg.slice(0, 60));

ok("the vocabulary is published", String(await view("vocabulary")).includes("len") && !String(await view("vocabulary")).includes("range"),
   String(await view("vocabulary")));

console.log(`\n${pass} passed, ${fail} failed`);
console.log("contract:", A);
