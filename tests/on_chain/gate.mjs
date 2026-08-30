/* The point of the whole contract: another contract enforcing a rule set with
 * no model, no consensus on the judgement, and no cost beyond the gas it was
 * already spending.
 *
 * Gate is a submission box that accepts a post only when a named Codify rule
 * set says it may. It calls check() synchronously through
 * gl.get_contract_at(...).view().
 *
 *   npm i genlayer-js viem && node tests/on_chain/gate.mjs
 *
 * Set the CODIFY environment variable to a deployed Codify holding a rule set
 * named "no-spam", or edit the default below.
 */
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { generatePrivateKey } from "viem/accounts";
import { readFileSync } from "node:fs";
const RPC="https://studio.genlayer.com/api";
const rpc=async(m,p)=>{const r=await fetch(RPC,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({jsonrpc:"2.0",id:1,method:m,params:p})});return (await r.json()).result;};
let pass=0,fail=0;
const ok=(n,c,d="")=>{c?pass++:fail++;console.log(`${c?"PASS":"FAIL"}  ${n}${d?"  — "+d:""}`);};
/* A Codify holding a rule set named "no-spam". Override it when you run this
   against your own: CODIFY=0x… node tests/on_chain/gate.mjs */
const CODIFY = process.env.CODIFY || "0x37c472780A4F20F12356010cba0D72686FCa6083";
const acc=createAccount(generatePrivateKey());
await rpc("sim_fundAccount",{account_address:acc.address,amount:300e18});
const c=createClient({chain:studionet,account:acc}), rd=createClient({chain:studionet});
const h=await c.deployContract({code:readFileSync(new URL("../../contracts/fixtures/gate.py", import.meta.url)),args:[CODIFY,"no-spam"],leaderOnly:false});
const G=(await c.waitForTransactionReceipt({hash:h,status:"ACCEPTED",retries:40,interval:4000}))?.data?.contract_address;
console.log("Gate at",G,"reading Codify at",CODIFY,"\n");
const send=async(text)=>{
  const t=await c.writeContract({address:G,functionName:"post",args:[text]});
  for(let i=0;i<45;i++){
    await new Promise(r=>setTimeout(r,4000));
    const tx=await rpc("eth_getTransactionByHash",[t]);
    if(tx?.status==="CANCELED") return {msg:"CANCELED",exec:"CANCELED",votes:{}};
    if(tx?.status==="FINALIZED"){
      const lr=tx.consensus_data?.leader_receipt,one=Array.isArray(lr)?lr[0]:lr;
      let m="";try{m=Buffer.from(one.result,"base64").toString("utf8").replace(/[^\x20-\x7e]/g," ").trim();}catch(e){}
      let a=0,d=0,idl=0;for(const k in (tx.consensus_data?.votes||{})){const v=tx.consensus_data.votes[k];if(v==="agree")a++;else if(v==="disagree")d++;else idl++;}
      let j=null;const b=m.indexOf("{");if(b!==-1){try{j=JSON.parse(m.slice(b));}catch(e){}}
      return {msg:m,exec:one?.execution_result,votes:{a,d,idl},j};
    }
  }
  return {msg:"TIMEOUT",exec:"",votes:{}};
};
const tally=(r)=>`${r.votes.a} agree, ${r.votes.d} disagree, ${r.votes.idl} idle`;

const good=await send("an ordinary post with #one #two");
ok("a clean post is accepted through the rule set", good.j?.ok===true, `${tally(good)} → ${good.msg.slice(0,70)}`);
const bad=await send("buy now http://spam.example #a #b #c");
ok("a post breaking the rules is refused", bad.j?.ok===false, `${tally(bad)} → ${bad.msg.slice(0,90)}`);
ok("and the consumer is told which rules it broke", Array.isArray(bad.j?.broke)&&bad.j.broke.length>0, JSON.stringify(bad.j?.broke));

/* The whole reason for this fixture: a subject far past what a gen_call view
   can carry, going through the VM instead. */
const subject="ok. "+"words and more words. ".repeat(12);   // 268 chars: past the view limit, inside the rule
const long=await send(subject);
ok(`a ${subject.length} char subject works contract-to-contract, where a view call cannot carry it`,
   long.j?.ok===true, `${tally(long)} → ${long.msg.slice(0,60)}`);

ok("accepted posts were kept", Number(await rd.readContract({address:G,functionName:"count",args:[]}))===2,
   String(await rd.readContract({address:G,functionName:"count",args:[]})));
ok("refusals were counted", Number(await rd.readContract({address:G,functionName:"rejections",args:[]}))===1);
console.log(`\n${pass} passed, ${fail} failed`);
console.log("gate:",G);
