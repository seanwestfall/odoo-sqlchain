// Explicitly a ChainSQL-owned demonstration merchant, not independent adoption.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {encodePaymentRequiredHeader,decodePaymentSignatureHeader,encodePaymentResponseHeader} from '@x402/core/http';
import {PaymentPayloadV2Schema} from '@x402/core/schemas';
import {requirement,NETWORK,facilitator,hash,canonical} from './protocol.mjs';
import {rpc,observe} from './adapter.mjs';
const directory=process.env.CHAINSQL_MERCHANT_JOURNAL;assert(directory);fs.mkdirSync(directory,{recursive:true,mode:0o700});
const recipient=process.env.CIRCLE_RECIPIENT;assert.match(recipient,/^0x[0-9a-fA-F]{40}$/);
const inflight=new Map();
function save(file,v){const tmp=file+'.tmp';fs.writeFileSync(tmp,JSON.stringify(v),{mode:0o600});const fd=fs.openSync(tmp,'r');fs.fsyncSync(fd);fs.closeSync(fd);fs.renameSync(tmp,file);const d=fs.openSync(directory,'r');fs.fsyncSync(d);fs.closeSync(d);}
async function purchase(url,p){
 PaymentPayloadV2Schema.parse(p);assert.equal(p.x402Version,2);assert.equal(p.resource.url,url);
 assert.deepEqual(p.accepted,requirement({amount_atomic:'10000',destination:recipient}));
 const a=p.payload.authorization;assert.equal(a.to.toLowerCase(),recipient.toLowerCase());assert.equal(a.value,'10000');assert.match(a.nonce,/^0x[0-9a-f]{64}$/);
 const key=hash([a.from.toLowerCase(),a.nonce]);const file=path.join(directory,key+'.json');
 let record=fs.existsSync(file)?JSON.parse(fs.readFileSync(file)):null;
 const digest=hash(p);
 if(record){assert.equal(record.digest,digest);assert.equal(record.url,url);}else{
  const verify=await facilitator('verify',{x402Version:2,paymentPayload:p,paymentRequirements:p.accepted});assert.equal(verify.isValid,true);
  record={url,digest,fromBlock:String(await rpc.getBlockNumber()),state:'pending'};save(file,record);
 }
 if(!record.settlement){
  const found=await observe(p,record.fromBlock);
  if(found&&!found.pending)record.settlement={success:true,transaction:found.transaction,network:NETWORK,payer:a.from};
  else if(found?.pending)return {pending:true};
  else {
   const outcome=await facilitator('settle',{x402Version:2,paymentPayload:p,paymentRequirements:p.accepted});
   if(outcome.success)record.settlement=outcome;
   else {record.lastError='settlement_unresolved';save(file,record);return {pending:true};}
  }
  save(file,record);
 }
 // The resource is a reproducible synthetic test fixture. No compliance claim.
 record.result??={demonstration:true,provider:'ChainSQL demo merchant',resourceVersion:'1',vendorId:new URL(url).pathname.split('/').pop(),verification:'synthetic_fixture_only',checks:{registry:'not_queried',sanctions:'not_queried',paymentInstructions:'requires_human_review'},explanation:'Demonstrates buying a vendor-verification response. This is not independent vendor due diligence.'};
 save(file,record);return record;
}
http.createServer(async(req,res)=>{
 const pathname=req.url;
 if(req.method!=='GET'||!/^\/vendor-verification\/[1-9][0-9]*\?version=1$/.test(pathname)){res.writeHead(404);res.end();return;}
 const url='http://127.0.0.1:8094'+pathname;
 if(!req.headers['payment-signature']){
  const challenge={x402Version:2,resource:{url,description:'ChainSQL demonstration vendor verification (synthetic fixture)',mimeType:'application/json'},accepts:[requirement({amount_atomic:'10000',destination:recipient})],extensions:{chainsql:{resourceVersion:'1',demonstration:true}}};
  res.writeHead(402,{'PAYMENT-REQUIRED':encodePaymentRequiredHeader(challenge),'Content-Type':'application/json'});res.end(JSON.stringify({demonstration:true,paymentRequired:true}));return;
 }
 try{
  assert(req.headers['payment-signature'].length<16384);const p=decodePaymentSignatureHeader(req.headers['payment-signature']);const key=hash([p.payload.authorization.from,p.payload.authorization.nonce]);
  const requestDigest=hash([url,p]);
  if(inflight.has(key))assert.equal(inflight.get(key).digest,requestDigest);
  else inflight.set(key,{digest:requestDigest,promise:purchase(url,p).finally(()=>inflight.delete(key))});
  const record=await inflight.get(key).promise;if(record.pending){res.writeHead(202);res.end('{"state":"pending_settlement"}');return;}
  res.writeHead(200,{'Content-Type':'application/json','PAYMENT-RESPONSE':encodePaymentResponseHeader(record.settlement)});res.end(JSON.stringify(record.result));
 }catch{res.writeHead(202,{'Content-Type':'application/json'});res.end('{"state":"needs_reconciliation"}');}
}).listen(8094,'127.0.0.1',()=>console.log('ChainSQL demonstration merchant listening on 127.0.0.1:8094'));
