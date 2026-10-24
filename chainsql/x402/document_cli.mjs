import fs from 'node:fs';
import {documentMatches,publish,verifyChain,rpc} from './document_commitment.mjs';
// CLI-only, trusted operator. Never exposed as an Odoo/agent tool.
const [mode,...args]=process.argv.slice(2);
try{
 if(mode==='verify'){
  const [document,manifestFile,transaction,publisher]=args,m=JSON.parse(fs.readFileSync(manifestFile));
  if(!documentMatches(fs.readFileSync(document),m))throw Error('byte_mismatch');
  const result=transaction?await verifyChain(rpc,m.commitment,transaction,publisher):{bytesMatch:true,chainChecked:false};
  console.log(JSON.stringify(result));
 }else if(mode==='publish'){
  const [approvalFile,signedFile,journal]=args;
  const result=await publish(JSON.parse(fs.readFileSync(approvalFile)),fs.readFileSync(signedFile,'utf8').trim(),journal);
  console.log(JSON.stringify(result));
 }else throw Error('Use verify DOCUMENT MANIFEST [TX PUBLISHER], or publish APPROVAL SIGNED_TX JOURNAL');
}catch{console.error('Document/approval verification failed or provider unavailable. No new authorization was generated.');process.exitCode=1;}
