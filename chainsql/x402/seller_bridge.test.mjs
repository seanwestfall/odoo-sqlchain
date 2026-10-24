import test from 'node:test';import assert from 'node:assert/strict';import {spawnSync} from 'node:child_process';import {privateKeyToAccount} from 'viem/accounts';import {domain,TYPES} from './protocol.mjs';
const account=privateKeyToAccount('0x'+'11'.repeat(32)); // PUBLIC TEST KEY
const until=Math.floor(Date.now()/1000)+600;
const requirements={scheme:'exact',network:'eip155:84532',asset:domain.verifyingContract,amount:'10000',payTo:'0x'+'22'.repeat(20),maxTimeoutSeconds:3600,extra:{name:'USDC',version:'2'}};
const resource={url:'http://127.0.0.1:8096/resources/00000000-0000-0000-0000-000000000001',description:'Approved immutable document snapshot',mimeType:'application/octet-stream'};
const authorization={from:account.address,to:requirements.payTo,value:'10000',validAfter:String(until-605),validBefore:String(until),nonce:'0x'+'33'.repeat(32)};
const signature=await account.signTypedData({domain,types:TYPES,primaryType:'TransferWithAuthorization',message:authorization});
const payload={x402Version:2,resource,accepted:requirements,payload:{signature,authorization}};
function run(p=payload,extra={}){return spawnSync(process.execPath,[new URL('./seller_bridge.mjs',import.meta.url).pathname],{input:JSON.stringify({operation:'validate',payload:p,requirements,resource,wallet:account.address.toLowerCase(),until,replay:false,...extra}),encoding:'utf8'});}
test('SDK v2 types and real EIP-712 authorization accepted',()=>assert.equal(run().status,0));
test('wrong buyer identity rejected',()=>assert.notEqual(run(payload,{wallet:'0x'+'44'.repeat(20)}).status,0));
test('changed resource rejected',()=>assert.notEqual(run({...payload,resource:{...resource,url:resource.url+'evil'}}).status,0));
test('changed amount rejected',()=>assert.notEqual(run({...payload,payload:{signature,authorization:{...authorization,value:'1'}}}).status,0));
test('changed signing domain rejected',async()=>{const bad=await account.signTypedData({domain:{...domain,chainId:1},types:TYPES,primaryType:'TransferWithAuthorization',message:authorization});assert.notEqual(run({...payload,payload:{signature:bad,authorization}}).status,0);});
test('grant shorter than authorization rejected',()=>assert.notEqual(run(payload,{until:until-1}).status,0));
