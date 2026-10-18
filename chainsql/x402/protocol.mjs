import assert from 'node:assert/strict';
import http from 'node:http';
import {createHash} from 'node:crypto';
import {decodePaymentRequiredHeader,encodePaymentSignatureHeader,decodePaymentResponseHeader} from '@x402/core/http';
import {PaymentRequiredV2Schema,PaymentPayloadV2Schema} from '@x402/core/schemas';
export const NETWORK='eip155:84532', TOKEN='0x036CbD53842c5426634e7929541eC2318f3dCF7e';
export const FACILITATOR='https://www.x402.org/facilitator';
export const TYPES={TransferWithAuthorization:[{name:'from',type:'address'},{name:'to',type:'address'},{name:'value',type:'uint256'},{name:'validAfter',type:'uint256'},{name:'validBefore',type:'uint256'},{name:'nonce',type:'bytes32'}]};
export const domain={name:'USDC',version:'2',chainId:84532,verifyingContract:TOKEN};
export function canonical(v){return JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);}
export function hash(v){return createHash('sha256').update(typeof v==='string'?v:canonical(v)).digest('hex');}
export function requirement(s){return {scheme:'exact',network:NETWORK,asset:TOKEN,amount:s.amount_atomic,payTo:s.destination,maxTimeoutSeconds:3600,extra:{name:'USDC',version:'2'}};}
export function validateRequest(s,r){
 assert.equal(s.network,NETWORK);assert.equal(s.interface,'x402-eip3009-6');assert.equal(s.fee_ceiling_atomic,'0');
 assert.match(s.amount_atomic,/^[1-9][0-9]*$/);assert.equal(r.scheme,'exact');assert.equal(r.asset,TOKEN);
 assert.equal(r.domain_name,'USDC');assert.equal(r.domain_version,'2');assert.equal(r.resource_version,'1');assert.equal(r.resource_key,'demo-vendor-verification');
 assert.equal(r.method,'GET');assert.equal(r.body,'');assert.match(r.url,/^http:\/\/127\.0\.0\.1:8094\/vendor-verification\/[1-9][0-9]*\?version=1$/);
}
// Only a literal loopback address and one exact route family are permitted in this demo.
// No DNS lookup, redirect following, arbitrary headers, proxy env, or supplied method/body.
export function resourceHTTP(r,payment){
 validateRequest({network:NETWORK,interface:'x402-eip3009-6',fee_ceiling_atomic:'0',amount_atomic:'1'},r);
 return new Promise((resolve,reject)=>{
  const req=http.get(r.url,{headers:payment?{'PAYMENT-SIGNATURE':encodePaymentSignatureHeader(payment)}:{},timeout:10000},res=>{
   let size=0;const chunks=[];res.on('data',b=>{size+=b.length;if(size>65536){res.destroy();reject(new Error('resource_too_large'));}else chunks.push(b);});
   res.on('error',reject);res.on('end',()=>{if(res.statusCode>=300&&res.statusCode<400)return reject(new Error('redirect_blocked'));resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks).toString()});});
  });req.on('timeout',()=>req.destroy(new Error('resource_timeout')));req.on('error',reject);
 });
}
export function validateChallenge(s,r,response,{alreadyPaid=false}={}){
 validateRequest(s,r);assert.equal(response.status,402);const raw=response.headers['payment-required'];assert(raw&&raw.length<16384);
 const challenge=decodePaymentRequiredHeader(raw);PaymentRequiredV2Schema.parse(challenge);
 assert.equal(challenge.x402Version,2);assert.equal(challenge.resource.url,r.url);assert.equal(challenge.resource.mimeType,'application/json');
 assert.equal(challenge.accepts.length,1);assert.deepEqual(challenge.accepts[0],requirement(s));
 assert.equal(challenge.extensions?.chainsql?.resourceVersion,r.resource_version);
 if(!alreadyPaid){const now=Date.now();assert(Date.parse(s.valid_from)<=now);assert(Date.parse(s.valid_until)>now);assert(Date.parse(s.valid_until)<=now+challenge.accepts[0].maxTimeoutSeconds*1000);}
 return challenge;
}
export function authorization(s,sender,fingerprint){return {from:sender,to:s.destination,value:s.amount_atomic,validAfter:String(Math.floor(Date.parse(s.valid_from)/1000)),validBefore:String(Math.floor(Date.parse(s.valid_until)/1000)),nonce:'0x'+fingerprint};}
export function typed(s,sender,fingerprint){return {domain,types:TYPES,primaryType:'TransferWithAuthorization',message:authorization(s,sender,fingerprint)};}
/** @returns {import('@x402/core/types').PaymentPayload} */
export function payload(s,r,sender,fp,signature){const p={x402Version:2,resource:{url:r.url,description:'ChainSQL demonstration vendor verification (synthetic fixture)',mimeType:'application/json'},accepted:requirement(s),payload:{signature,authorization:authorization(s,sender,fp)}};PaymentPayloadV2Schema.parse(p);return p;}
export async function facilitator(path,body){
 assert(['supported','verify','settle'].includes(path));
 const res=await fetch(FACILITATOR+'/'+path,{method:body?'POST':'GET',redirect:'error',signal:AbortSignal.timeout(20000),headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
 const chunks=[];let size=0;
 for await(const chunk of res.body){size+=chunk.length;assert(size<65536,'facilitator_response_too_large');chunks.push(Buffer.from(chunk));}
 assert(res.ok,'facilitator_unavailable');return JSON.parse(Buffer.concat(chunks).toString());
}
export function paymentResponse(response){const h=response.headers['payment-response'];assert(h&&h.length<16384);return decodePaymentResponseHeader(h);}
