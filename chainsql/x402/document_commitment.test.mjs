import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {createHash} from 'node:crypto';
import {privateKeyToAccount} from 'viem/accounts';
import {documentMatches,validateSigned,verifyChain,publish,TAG,CHAIN} from './document_commitment.mjs';
const account=privateKeyToAccount('0x'+'11'.repeat(32)); // PUBLIC TEST KEY; never funded
const bytes=Buffer.from('synthetic certificate\r\n'),salt=Buffer.alloc(32,2);
const sha=b=>createHash('sha256').update(b).digest('hex');
const manifest={sha256:sha(bytes),salt:salt.toString('hex'),commitment:sha(Buffer.concat([Buffer.from('ChainSQL/document-commitment/v1\0'),salt,Buffer.from(sha(bytes),'hex')]))};
const approval={approval_id:'synthetic-test',approved_by:'test-operator',commitment:manifest.commitment,dedicated_wallet:true,fee_ceiling_atomic:'100000',nonce:'0',policy_version:'document-publication-v1',publisher:account.address,valid_until:new Date(Date.now()+600000).toISOString()};
const transaction={type:'eip1559',chainId:CHAIN,to:account.address,value:0n,nonce:0,gas:30000n,maxFeePerGas:2n,maxPriorityFeePerGas:1n,data:'0x'+TAG+manifest.commitment};
const raw=await account.signTransaction(transaction),hash=await validateSigned(approval,raw);
function client(){return {getChainId:async()=>CHAIN,getTransaction:async()=>({hash,from:account.address,to:account.address,value:0n,input:transaction.data}),getTransactionReceipt:async()=>({transactionHash:hash,status:'success',blockNumber:10n,blockHash:'0xabc',gasUsed:22000n,effectiveGasPrice:2n}),getBlock:async x=>x.blockTag?{number:10n}:{hash:'0xabc'}};}
test('exact-byte proof and changed bytes',()=>{assert(documentMatches(bytes,manifest));assert(!documentMatches(Buffer.concat([bytes,Buffer.from(' ')]),manifest));});
test('salt is not in the public commitment payload',()=>assert(!transaction.data.includes(salt.toString('hex'))));
test('approved raw transaction is bound to exact commitment and zero value',async()=>assert.equal(await validateSigned(approval,raw),hash));
for(const [name,change] of Object.entries({recipient:{to:'0x'+'22'.repeat(20)},value:{value:1n},data:{data:'0x1234'},nonce:{nonce:1},chain:{chainId:1},fee:{maxFeePerGas:999n}}))test('reject changed '+name,async()=>{await assert.rejects(()=>account.signTransaction({...transaction,...change}).then(r=>validateSigned(approval,r)));});
test('independent verifier reads canonical finalized chain record',async()=>assert.equal((await verifyChain(client(),manifest.commitment,hash,account.address)).transaction,hash));
test('independent verifier rejects changed chain data',async()=>{const c=client();c.getTransaction=async()=>({hash,from:account.address,to:account.address,value:0n,input:'0x1234'});await assert.rejects(()=>verifyChain(c,manifest.commitment,hash,account.address));});
test('independent verifier rejects unfinalized receipt',async()=>{const c=client();c.getBlock=async x=>x.blockTag?{number:9n}:{hash:'0xabc'};await assert.rejects(()=>verifyChain(c,manifest.commitment,hash,account.address));});
test('persist before transmission; timeout recovers original hash',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'chainsql-commit-'));let sent=0,exists=false;const c=client(),get=c.getTransaction;
 c.getTransaction=async()=>{if(!exists){const e=new Error();e.name='TransactionNotFoundError';throw e;}return get();};
 c.sendRawTransaction=async x=>{assert.equal(x.serializedTransaction,raw);assert.equal(fs.readdirSync(dir).length,1);sent++;exists=true;throw Error('lost response');};
 assert.equal((await publish(approval,raw,dir,c)).state,'uncertain');assert.equal((await publish(approval,raw,dir,c)).state,'confirmed');assert.equal(sent,1);
 const other={...approval,commitment:'ab'.repeat(32)},raw2=await account.signTransaction({...transaction,data:'0x'+TAG+other.commitment});await assert.rejects(()=>publish(other,raw2,dir,c));
 fs.rmSync(dir,{recursive:true});
});
