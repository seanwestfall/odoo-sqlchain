import test from 'node:test';
import assert from 'node:assert/strict';
import { privateKeyToAccount } from '../../milestone0/wallet/node_modules/viem/_esm/accounts/index.js';
import { encodeEventTopics, encodeAbiParameters, keccak256 } from '../../milestone0/wallet/node_modules/viem/_esm/index.js';
import { ARC, ABI } from '../../milestone0/wallet/network.mjs';
import { ArcAdapter, configuredAdapter, transactionFor, validateSigned } from './adapter.mjs';
const account=privateKeyToAccount('0x'+'11'.repeat(32));
const destination='0x2222222222222222222222222222222222222222';
const hash='0x'+'ab'.repeat(32);
function fixture() {
  const s={network:ARC.network,asset:'USDC',interface:'arc-erc20-6-fee18',source_wallet:'wallet-fixture',destination,
    amount_atomic:'10000',fee_ceiling_atomic:'50000000000000000'};
  let receipt=null, raw=null, signed=0, broadcasts=0, loseResponse=false;
  const missing=()=>Object.assign(new Error('not found'),{name:'TransactionReceiptNotFoundError'});
  const rpc={getChainId:async()=>ARC.chainId,readContract:async()=>6,getBalance:async()=>10n**18n,
    estimateGas:async()=>21000n,getGasPrice:async()=>2_000_000_000n,getTransactionCount:async()=>0,
    getTransactionReceipt:async()=>{if(!receipt)throw missing();return receipt;},
    getBlock:async({blockNumber})=>({number:blockNumber??12n,hash}),
    sendRawTransaction:async({serializedTransaction})=>{broadcasts++;raw=serializedTransaction;if(loseResponse)throw new Error('timeout');return keccak256(raw);}};
  const circle={getWallet:async()=>({data:{wallet:{address:account.address,blockchain:'EVM-TESTNET',accountType:'EOA'}}}),
    signTransaction:async({transaction,xRequestId})=>{
      signed++;assert.match(xRequestId,/^[0-9a-f-]{36}$/);
      const tx=JSON.parse(transaction);
      const raw=await account.signTransaction({chainId:tx.chainId,nonce:Number(tx.nonce),to:tx.to,value:BigInt(tx.value),
        gas:BigInt(tx.gas),maxFeePerGas:BigInt(tx.maxFeePerGas),maxPriorityFeePerGas:BigInt(tx.maxPriorityFeePerGas),data:tx.data,type:'eip1559'});
      return {data:{signedTransaction:raw,txHash:keccak256(raw)}};
    }};
  const adapter=new ArcAdapter({rpc,circle,walletId:'wallet-fixture'});
  return {s,rpc,circle,adapter,counts:()=>({signed,broadcasts}),lose:()=>loseResponse=true,
    receipt:(txHash,status='success')=>{receipt={transactionHash:txHash,blockHash:hash,blockNumber:10n,status,
      gasUsed:21000n,effectiveGasPrice:2_000_000_000n,logs:status==='success'?[{address:ARC.token,
        topics:encodeEventTopics({abi:ABI,eventName:'Transfer',args:{from:account.address,to:destination}}),
        data:encodeAbiParameters([{type:'uint256'}],[10000n])}]:[]};},
    clear:()=>receipt=null};
}
async function prepared(f) { const p=await f.adapter.prepare(f.s);return {...p,nonce:p.pendingNonce,providerRequestId:'11111111-1111-4111-8111-111111111111'}; }
test('missing Circle server credentials fail closed',()=>assert.throws(()=>configuredAdapter({}),/circle_configuration_required/));
test('6 decimal transfer and 18 decimal fee preparation',async()=>{const f=fixture(),p=await prepared(f);assert.equal(transactionFor(f.s,p).value,0n);assert.equal(p.nonce,'0');});
test('wrong chain rejected',async()=>{const f=fixture();f.rpc.getChainId=async()=>1;await assert.rejects(()=>prepared(f),/wrong_network/);});
test('native Arc wallet is not silently substituted for documented signing wallet',async()=>{const f=fixture();f.circle.getWallet=async()=>({data:{wallet:{blockchain:'ARC-TESTNET',accountType:'EOA'}}});await assert.rejects(()=>prepared(f),/signing_wallet_required/);});
test('insufficient balance rejected before signing',async()=>{const f=fixture();f.rpc.getBalance=async()=>0n;await assert.rejects(()=>prepared(f),/insufficient_balance/);assert.equal(f.counts().signed,0);});
test('fee ceiling rejected before signing',async()=>{const f=fixture();f.s.fee_ceiling_atomic='1';await assert.rejects(()=>prepared(f),/fee_ceiling_exceeded/);});
test('signed nonce, sender and recipient are checked',async()=>{const f=fixture(),p=await prepared(f),a=await f.adapter.sign(f.s,p);assert.equal(await validateSigned(f.s,p,a.raw),a.txHash);await assert.rejects(()=>validateSigned({...f.s,destination:account.address},p,a.raw));await assert.rejects(()=>validateSigned(f.s,{...p,nonce:'1'},a.raw));});
test('lost response recovers by original hash without another signature or payment',async()=>{const f=fixture(),p=await prepared(f),a=await f.adapter.sign(f.s,p);f.lose();assert.equal((await f.adapter.submit(f.s,p,a)).state,'uncertain');f.receipt(a.txHash);const observed=await f.adapter.reconcile(f.s,p,a);assert.equal(observed.state,'confirmed');assert.equal(observed.feeAtomic,'42000000000000');assert.equal(observed.amountDecimals,6);assert.equal(observed.feeDecimals,18);assert.deepEqual(f.counts(),{signed:1,broadcasts:1});});
test('replay finds the original receipt and does not broadcast',async()=>{const f=fixture(),p=await prepared(f),a=await f.adapter.sign(f.s,p);f.receipt(a.txHash);assert.equal((await f.adapter.submit(f.s,p,a)).state,'receipt_available');assert.equal(f.counts().broadcasts,0);});
test('pending receipt is uncertain, never treated as failed or paid',async()=>{const f=fixture(),p=await prepared(f),a=await f.adapter.sign(f.s,p);assert.equal((await f.adapter.reconcile(f.s,p,a)).state,'uncertain');assert.equal(f.counts().signed,1);});
test('reverted receipt reports gas without claiming payment',async()=>{const f=fixture(),p=await prepared(f),a=await f.adapter.sign(f.s,p);f.receipt(a.txHash,'reverted');assert.equal((await f.adapter.observe(f.s,p,a)).state,'reverted');});
test('receipt below finality threshold remains confirming',async()=>{const f=fixture(),p=await prepared(f),a=await f.adapter.sign(f.s,p);f.receipt(a.txHash);f.rpc.getBlock=async({blockNumber})=>({number:blockNumber??9n,hash});assert.equal((await f.adapter.observe(f.s,p,a)).state,'confirming');});
test('unavailable provider does not authorize replacement signing',async()=>{const f=fixture(),p=await prepared(f),a=await f.adapter.sign(f.s,p);f.rpc.getTransactionReceipt=async()=>{throw new Error('503');};await assert.rejects(()=>f.adapter.observe(f.s,p,a),/provider_unavailable/);assert.equal(f.counts().signed,1);});
