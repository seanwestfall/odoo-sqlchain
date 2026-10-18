import {readFile,writeFile} from 'node:fs/promises';
const state=JSON.parse(await readFile(new URL('../../.local/circle_wallet/circle-setup.json',import.meta.url),'utf8'));
try {
 const result=await fetch('https://api.circle.com/v1/faucet/drips',{method:'POST',headers:{Authorization:'Bearer '+process.env.CIRCLE_API_KEY,'Content-Type':'application/json'},body:JSON.stringify({address:state.wallets[0].address,blockchain:'ARC-TESTNET',usdc:true}),signal:AbortSignal.timeout(30000)});
 if (!result.ok) {const e=await result.json();console.log(JSON.stringify({httpStatus:result.status,circleCode:e.code??null}));process.exit(2);}
 const evidence={requestedAt:new Date().toISOString(),httpStatus:result.status,address:state.wallets[0].address,network:'ARC-TESTNET'};
 await writeFile(new URL('../../milestone3/evidence/faucet.json',import.meta.url),JSON.stringify(evidence,null,2)+'\n');console.log(JSON.stringify(evidence));
} catch(e) {console.log(JSON.stringify({httpStatus:e.response?.status??null,circleCode:e.response?.data?.code??null,error:'faucet_request_failed'}));process.exitCode=2;}
