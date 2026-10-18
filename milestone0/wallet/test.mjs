import test from 'node:test';
import assert from 'node:assert/strict';
import { encodeEventTopics, encodeAbiParameters, decodeFunctionData, encodeFunctionData } from 'viem';
import { ARC, ABI, AMOUNT_ATOMIC, calldata, validateReceipt } from './network.mjs';
const sender = '0x1111111111111111111111111111111111111111';
const recipient = '0x2222222222222222222222222222222222222222';
const hash = `0x${'11'.repeat(32)}`;
const blockHash = `0x${'22'.repeat(32)}`;
function fixture() {
  const log = {address:ARC.token,
    topics:encodeEventTopics({abi:ABI,eventName:'Transfer',args:{from:sender,to:recipient}}),
    data:encodeAbiParameters([{type:'uint256'}],[AMOUNT_ATOMIC])};
  return {sender,recipient,transaction:{chainId:ARC.chainId,from:sender,to:ARC.token,value:0n,input:calldata(recipient),hash},
    receipt:{status:'success',transactionHash:hash,blockHash,blockNumber:10n,gasUsed:50_000n,effectiveGasPrice:20_000_000_000n,logs:[log]},
    block:{number:10n,hash:blockHash}};
}
test('0.01 USDC is 10000 ERC-20 atomic units',()=>{
  const decoded = decodeFunctionData({abi:ABI,data:calldata(recipient)});
  assert.equal(decoded.args[1],10_000n);
});
test('receipt separates transfer and gas precision',()=>{
  const result = validateReceipt(fixture());
  assert.equal(result.amountAtomic,'10000'); assert.equal(result.amountDecimals,6);
  assert.equal(result.feeAtomic,'1000000000000000'); assert.equal(result.feeDecimals,18);
});
test('18-decimal system event does not double-count payment',()=>{
  const f=fixture();
  f.receipt.logs.push({...f.receipt.logs[0],address:'0xfffffffffffffffffffffffffffffffffffffffe',
    data:encodeAbiParameters([{type:'uint256'}],[AMOUNT_ATOMIC*10n**12n])});
  assert.equal(validateReceipt(f).matchingTransferLogs,1);
});
test('reject a native-value send',()=>{
  const f=fixture(); f.transaction.value=AMOUNT_ATOMIC*10n**12n;
  assert.throws(()=>validateReceipt(f),/native value/);
});
test('reject eighteen-decimal quantity in token transfer',()=>{
  const f=fixture(); f.transaction.input=encodeFunctionData({abi:ABI,functionName:'transfer',args:[recipient,AMOUNT_ATOMIC*10n**12n]});
  assert.throws(()=>validateReceipt(f));
});
test('reject wrong network, recipient, token, and block identity',()=>{
  for (const mutate of [f=>f.transaction.chainId=84532,f=>f.transaction.to=recipient,
    f=>f.recipient=sender,f=>f.block.hash=hash]) {
    const f=fixture(); mutate(f); assert.throws(()=>validateReceipt(f));
  }
});
test('reject reverted or missing transfer evidence',()=>{
  const f=fixture(); f.receipt.status='reverted'; assert.throws(()=>validateReceipt(f),/reverted/);
  f.receipt.status='success'; f.receipt.logs=[]; assert.throws(()=>validateReceipt(f),/matching/);
});
test('reject actual fee above the cap',()=>{
  const f=fixture(); f.receipt.gasUsed=10_000_000n; assert.throws(()=>validateReceipt(f),/fee/);
});
