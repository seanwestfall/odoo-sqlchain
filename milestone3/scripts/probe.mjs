// Read-only Arc identity, token precision, and finality-tag probe. Never signs or sends.
import { createPublicClient,http } from '../../milestone0/wallet/node_modules/viem/_esm/index.js';
import {ARC,ABI} from '../../milestone0/wallet/network.mjs';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
const rpc=createPublicClient({transport:http(ARC.rpc,{retryCount:0,timeout:20000})});
const [chainId,decimals,block]=await Promise.all([rpc.getChainId(),rpc.readContract({address:ARC.token,abi:ABI,functionName:'decimals'}),rpc.getBlock({blockTag:'finalized'})]);
assert.equal(chainId,5042002);assert.equal(Number(decimals),6);assert(block.hash);
const result={observedAt:new Date().toISOString(),rpc:ARC.rpc,chainId,asset:'USDC',token:ARC.token,tokenDecimals:Number(decimals),nativeFeeDecimals:18,finalizedBlockNumber:String(block.number),finalizedBlockHash:block.hash,transferPerformed:false};
await writeFile(new URL('../evidence/network.json',import.meta.url),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));
