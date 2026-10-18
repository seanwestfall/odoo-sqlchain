// Private child-process protocol. stdout can contain signed bytes and MUST be piped
// directly into the restricted controller, never logged or exposed as an agent tool.
import { configuredAdapter, validateSigned } from './adapter.mjs';
let input='';for await (const chunk of process.stdin) {input+=chunk;if(input.length>131072)throw new Error('request too large');}
try {
 const request=JSON.parse(input);
 if(request.operation==='validate') {
  console.log(JSON.stringify({txHash:await validateSigned(request.snapshot,request.plan,request.authorization.raw)}));
 } else {
  const adapter=configuredAdapter();
  if(!['prepare','sign','submit','observe','reconcile'].includes(request.operation))throw new Error('unsupported operation');
  const result=await adapter[request.operation](request.snapshot,request.plan,request.authorization);
  console.log(JSON.stringify(result));
 }
} catch(error) { console.log(JSON.stringify({error:error.code??(error.name==='AssertionError'?'verification_failed':'provider_unavailable')}));process.exitCode=2; }
