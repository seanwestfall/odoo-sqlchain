import assert from 'node:assert/strict';
import {createPublicClient,http,parseAbi,recoverTypedDataAddress,decodeEventLog} from 'viem';
import {initiateDeveloperControlledWalletsClient} from '../../milestone0/wallet/node_modules/@circle-fin/developer-controlled-wallets/dist/developer-controlled-wallets.es.js';
import {NETWORK,TOKEN,domain,typed,payload,facilitator,validateRequest,authorization} from './protocol.mjs';
export const ABI=parseAbi(['function balanceOf(address) view returns (uint256)','function name() view returns (string)','function version() view returns (string)','function decimals() view returns (uint8)','function authorizationState(address,bytes32) view returns (bool)','event AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce)','event Transfer(address indexed from,address indexed to,uint256 value)']);
export const rpc=createPublicClient({transport:http('https://sepolia.base.org',{timeout:15000,retryCount:0})});
export async function probe(sender){
 assert.equal(await rpc.getChainId(),84532);
 for(const [functionName,expected] of [['name','USDC'],['version','2'],['decimals',6]]) assert.equal(await rpc.readContract({address:TOKEN,abi:ABI,functionName}),expected);
 const supported=await facilitator('supported');assert(supported.kinds.some(k=>k.x402Version===2&&k.scheme==='exact'&&k.network===NETWORK));
 return {supported,balance:String(await rpc.readContract({address:TOKEN,abi:ABI,functionName:'balanceOf',args:[sender]})),block:String(await rpc.getBlockNumber())};
}
export async function validate(s,r,fp,p){
 validateRequest(s,r);assert.equal(p.x402Version,2);assert.deepEqual(p.payload.authorization,authorization(s,p.payload.authorization.from,fp));
 const expected=payload(s,r,p.payload.authorization.from,fp,p.payload.signature);assert.deepEqual(p,expected);
 assert.equal((await recoverTypedDataAddress({...typed(s,p.payload.authorization.from,fp),signature:p.payload.signature})).toLowerCase(),p.payload.authorization.from.toLowerCase());
}
export async function sign(s,r,fp,env=process.env){
 validateRequest(s,r);assert.equal(s.source_wallet,env.CIRCLE_SIGNING_WALLET_ID);assert(env.CIRCLE_API_KEY?.startsWith('TEST_API_KEY:'));
 const circle=initiateDeveloperControlledWalletsClient({apiKey:env.CIRCLE_API_KEY,entitySecret:env.CIRCLE_ENTITY_SECRET});
 const w=(await circle.getWallet({id:s.source_wallet})).data.wallet;assert.equal(w.blockchain,'EVM-TESTNET');assert.equal(w.accountType,'EOA');
 const check=await probe(w.address);assert(BigInt(check.balance)>=BigInt(s.amount_atomic),'insufficient_test_USDC');
 const td=typed(s,w.address,fp);td.types={EIP712Domain:[{name:'name',type:'string'},{name:'version',type:'string'},{name:'chainId',type:'uint256'},{name:'verifyingContract',type:'address'}],...td.types};
 const result=await circle.signTypedData({walletId:s.source_wallet,data:JSON.stringify(td)});
 const p=payload(s,r,w.address,fp,result.data.signature);await validate(s,r,fp,p);return {payment:p,fromBlock:check.block};
}
// Receipt must contain both the exact nonce consumption and token transfer. A
// facilitator response alone is never sufficient evidence of observed spend.
export async function observe(p,fromBlock,transaction){
 const a=p.payload.authorization;
 if(!transaction){
  const logs=await rpc.getLogs({address:TOKEN,event:ABI.find(x=>x.name==='AuthorizationUsed'),args:{authorizer:a.from,nonce:a.nonce},fromBlock:BigInt(fromBlock),toBlock:'latest'});
  if(!logs.length)return null;assert.equal(logs.length,1);transaction=logs[0].transactionHash;
 }
 let receipt;try{receipt=await rpc.getTransactionReceipt({hash:transaction});}catch(e){if(e.name==='TransactionReceiptNotFoundError')return null;throw e;}
 assert.equal(receipt.status,'success');const block=await rpc.getBlock({blockNumber:receipt.blockNumber});assert.equal(block.hash,receipt.blockHash);
 const finalized=await rpc.getBlock({blockTag:'finalized'});if((await rpc.getBlockNumber())<receipt.blockNumber+2n)return {pending:true,transaction};
 const events=receipt.logs.filter(x=>x.address.toLowerCase()===TOKEN.toLowerCase()).flatMap(x=>{try{return [decodeEventLog({abi:ABI,...x})];}catch{return [];}});
 assert.equal(events.filter(e=>e.eventName==='AuthorizationUsed'&&e.args.authorizer.toLowerCase()===a.from.toLowerCase()&&e.args.nonce===a.nonce).length,1);
 assert.equal(events.filter(e=>e.eventName==='Transfer'&&e.args.from.toLowerCase()===a.from.toLowerCase()&&e.args.to.toLowerCase()===a.to.toLowerCase()&&e.args.value===BigInt(a.value)).length,1);
 return {transaction,network:NETWORK,amount:a.value,recipient:a.to,authorization_nonce:a.nonce,receipt_status:'success',blockNumber:String(receipt.blockNumber),blockHash:receipt.blockHash,finalizedBlock:String(finalized.number),finality:finalized.number>=receipt.blockNumber?'L1-finalized':'L2 receipt with 2 successor blocks; not L1-finalized',observedAt:new Date().toISOString(),payerFeeAtomic:'0',feeHandling:'facilitator pays Base Sepolia native ETH gas'};
}
