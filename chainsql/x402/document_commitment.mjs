// Optional operator-only Arc testnet publication. No private document bytes or salt leave this process.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createPublicClient,http,parseTransaction,recoverTransactionAddress,keccak256} from 'viem';
export const CHAIN=5042002;
export const TAG=Buffer.from('ChainSQL:document:v1:').toString('hex');
export const rpc=createPublicClient({transport:http('https://rpc.testnet.arc.io',{timeout:15000,retryCount:0})});
const sha=x=>createHash('sha256').update(x).digest('hex');
export function documentMatches(bytes,manifest){
 try{
  assert.match(manifest.salt,/^[a-f0-9]{64}$/);assert.match(manifest.sha256,/^[a-f0-9]{64}$/);assert.match(manifest.commitment,/^[a-f0-9]{64}$/);
  const digest=sha(bytes),commitment=sha(Buffer.concat([Buffer.from('ChainSQL/document-commitment/v1\0'),Buffer.from(manifest.salt,'hex'),Buffer.from(digest,'hex')]));
  return digest===manifest.sha256&&commitment===manifest.commitment;
 }catch{return false;}
}
export function validateApproval(a){
 assert.deepEqual(Object.keys(a).sort(),['approval_id','approved_by','commitment','dedicated_wallet','fee_ceiling_atomic','nonce','policy_version','publisher','valid_until'].sort());
 assert.equal(a.policy_version,'document-publication-v1');assert.equal(a.dedicated_wallet,true);
 assert.match(a.approval_id,/^[a-zA-Z0-9-]{1,100}$/);assert.equal(typeof a.approved_by,'string');assert(a.approved_by.length>0);
 assert.match(a.publisher,/^0x[0-9a-fA-F]{40}$/);assert.match(a.commitment,/^[0-9a-f]{64}$/);
 for(const name of ['nonce','fee_ceiling_atomic'])assert.match(a[name],/^(0|[1-9][0-9]{0,37})$/);
 assert(BigInt(a.fee_ceiling_atomic)>0n);assert(Number.isFinite(Date.parse(a.valid_until)));
}
export async function validateSigned(a,raw){
 validateApproval(a);const tx=parseTransaction(raw);assert.equal(tx.type,'eip1559');assert.equal(tx.chainId,CHAIN);
 assert.equal((await recoverTransactionAddress({serializedTransaction:raw})).toLowerCase(),a.publisher.toLowerCase());
 assert.equal(tx.to.toLowerCase(),a.publisher.toLowerCase());assert.equal(tx.value??0n,0n);
 assert.equal(BigInt(tx.nonce??0),BigInt(a.nonce));assert.equal(tx.data,'0x'+TAG+a.commitment);
 assert(tx.gas>=21000n);assert(tx.maxPriorityFeePerGas<=tx.maxFeePerGas);assert(tx.gas*tx.maxFeePerGas<=BigInt(a.fee_ceiling_atomic));
 assert(!tx.accessList?.length);return keccak256(raw);
}
export async function verifyChain(client,commitment,hash,publisher){
 assert.equal(await client.getChainId(),CHAIN);assert.match(commitment,/^[0-9a-f]{64}$/);
 const tx=await client.getTransaction({hash});assert.equal(tx.hash.toLowerCase(),hash.toLowerCase());
 assert.equal(tx.from.toLowerCase(),publisher.toLowerCase());assert.equal(tx.to.toLowerCase(),publisher.toLowerCase());assert.equal(tx.value,0n);assert.equal(tx.input,'0x'+TAG+commitment);
 const receipt=await client.getTransactionReceipt({hash});assert.equal(receipt.status,'success');assert.equal(receipt.transactionHash.toLowerCase(),hash.toLowerCase());
 const block=await client.getBlock({blockNumber:receipt.blockNumber});assert.equal(block.hash,receipt.blockHash);
 const finalized=await client.getBlock({blockTag:'finalized'});assert(finalized.number>=receipt.blockNumber,'not_finalized');
 return {chainId:CHAIN,transaction:hash,commitment,publisher,blockNumber:String(receipt.blockNumber),blockHash:receipt.blockHash,finalizedBlock:String(finalized.number),feeAtomic:String(receipt.gasUsed*receipt.effectiveGasPrice),observedAt:new Date().toISOString()};
}
export async function publish(a,raw,directory,client=rpc){
 const hash=await validateSigned(a,raw);assert.equal(await client.getChainId(),CHAIN);
 fs.mkdirSync(directory,{recursive:true,mode:0o700});
 const filename=path.join(directory,a.publisher.toLowerCase()+'-'+a.nonce+'.json');
 try{
  const fd=fs.openSync(filename,'wx',0o600);
  try{fs.writeFileSync(fd,JSON.stringify({approval:a,raw,hash}));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  const dir=fs.openSync(directory,'r');try{fs.fsyncSync(dir);}finally{fs.closeSync(dir);}
 }catch(e){
  if(e.code!=='EEXIST')throw e;
  const saved=JSON.parse(fs.readFileSync(filename));assert.equal(saved.hash,hash);assert.equal(saved.raw,raw);assert.deepEqual(saved.approval,a);
 }
 try{return {state:'confirmed',...await verifyChain(client,a.commitment,hash,a.publisher)};}catch(e){
  // A provider failure or not-yet-final receipt is uncertain. Never create a new nonce.
  if(!['TransactionNotFoundError','TransactionReceiptNotFoundError'].includes(e.name))return {state:'uncertain',hash,reason:'reconcile_original_hash'};
 }
 if(Date.now()>=Date.parse(a.valid_until))return {state:'uncertain',hash,reason:'approval_expired_no_new_broadcast'};
 try{assert.equal((await client.sendRawTransaction({serializedTransaction:raw})).toLowerCase(),hash);return {state:'submitted',hash};}
 catch{return {state:'uncertain',hash,reason:'reconcile_original_hash'};}
}
