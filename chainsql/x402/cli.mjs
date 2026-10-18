import {sign,validate,observe,probe} from './adapter.mjs';
import {resourceHTTP,validateChallenge,paymentResponse} from './protocol.mjs';
let input='';for await(const c of process.stdin)input+=c;
try{
 const {operation,snapshot:s,request:r,fingerprint:fp,authorization:a}=JSON.parse(input);let result;
 if(operation==='challenge'){const response=await resourceHTTP(r);validateChallenge(s,r,response);result={httpStatus:response.status,challenge:JSON.parse(Buffer.from(response.headers['payment-required'],'base64').toString())};}
 else if(operation==='sign')result=await sign(s,r,fp);
 else if(operation==='validate'){await validate(s,r,fp,a.payment);result={valid:true};}
 else if(operation==='observe')result=await observe(a.payment,a.fromBlock,a.transaction)||{pending:true};
 else if(operation==='purchase'||operation==='redeliver'){
  await validate(s,r,fp,a.payment);
  // Rechallenge on EVERY send; changed price/payee/version cannot reuse authority.
  let alreadyPaid=false;
  if(operation==='redeliver'){const receipt=await observe(a.payment,a.fromBlock,a.transaction);if(!receipt||receipt.pending)throw Error('not_observed');alreadyPaid=true;}
  validateChallenge(s,r,await resourceHTTP(r),{alreadyPaid});
  const response=await resourceHTTP(r,a.payment);
  let settlement=null; if(response.headers['payment-response'])settlement=paymentResponse(response);
  if(response.status===200&&settlement?.success)result={delivery:JSON.parse(response.body),settlement};
  else result={pending:true,httpStatus:response.status,settlement};
 }else throw Error('unsupported_operation');
 console.log(JSON.stringify(result));
}catch(e){console.log(JSON.stringify({error:e.code==='ERR_ASSERTION'?'policy_or_receipt_mismatch':e.message==='redirect_blocked'?'redirect_blocked':'provider_or_resource_unavailable'}));process.exitCode=1;}
