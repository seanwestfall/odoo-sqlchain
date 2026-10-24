// Fixed Base Sepolia exact/EIP-3009 path. No wallet keys or signing capability.
import assert from 'node:assert/strict';
import {PaymentPayloadV2Schema} from '@x402/core/schemas';
import {recoverTypedDataAddress} from 'viem';
import {domain,TYPES,facilitator} from './protocol.mjs';
import {rpc,observe} from './adapter.mjs';
let input='';for await(const c of process.stdin)input+=c;
try{
 const x=JSON.parse(input),p=x.payload;let result;
 if(x.operation==='validate'){
  assert.equal(x.requirements.network,'eip155:84532');assert.equal(x.requirements.scheme,'exact');assert.equal(x.requirements.asset,domain.verifyingContract);assert.deepEqual(x.requirements.extra,{name:'USDC',version:'2'});
  PaymentPayloadV2Schema.parse(p);assert.deepEqual(p.accepted,x.requirements);assert.deepEqual(p.resource,x.resource);
  const a=p.payload.authorization;assert.equal(a.from.toLowerCase(),x.wallet);assert.equal(a.to.toLowerCase(),x.requirements.payTo.toLowerCase());assert.equal(a.value,x.requirements.amount);
  const address=await recoverTypedDataAddress({domain,types:TYPES,primaryType:'TransferWithAuthorization',message:a,signature:p.payload.signature});assert.equal(address.toLowerCase(),x.wallet);
  if(!x.replay){const now=Math.floor(Date.now()/1000);assert(BigInt(a.validAfter)<=BigInt(now));assert(BigInt(a.validBefore)>BigInt(now));assert(BigInt(a.validBefore)<=BigInt(Math.min(x.until,now+3600)));}
  result={valid:true};
 }else if(x.operation==='verify'){
  assert.equal(await rpc.getChainId(),84532);const supported=await facilitator('supported');assert(supported.kinds.some(k=>k.x402Version===2&&k.scheme==='exact'&&k.network==='eip155:84532'));
  const v=await facilitator('verify',{x402Version:2,paymentPayload:p,paymentRequirements:x.requirements});assert.equal(v.isValid,true);result={block:String(await rpc.getBlockNumber())};
 }else if(x.operation==='settle')result=await facilitator('settle',{x402Version:2,paymentPayload:p,paymentRequirements:x.requirements});
 else if(x.operation==='observe')result=await observe(p,x.fromBlock)||{};
 else throw Error('unsupported');
 console.log(JSON.stringify(result));
}catch{console.log(JSON.stringify({error:'payment_validation_or_provider_failure'}));process.exitCode=1;}
