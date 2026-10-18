// Recover an ambiguous registration by testing the existing secret with the
// original idempotent wallet-set request. Never registers or rotates a secret.
import {readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {initiateDeveloperControlledWalletsClient} from '../../milestone0/wallet/node_modules/@circle-fin/developer-controlled-wallets/dist/developer-controlled-wallets.es.js';
process.umask(0o077);
const root=new URL('../../.local/circle_wallet/',import.meta.url),file=new URL('circle-setup.json',root),lock=new URL('circle-setup.lock/',root);
await mkdir(lock);
try {
 const state=JSON.parse(await readFile(file,'utf8'));
 assert.equal(state.keyFingerprint,createHash('sha256').update(process.env.CIRCLE_API_KEY??'').digest('hex'));
 assert(state.registrationStarted && !state.registered && state.walletSetRequest?.idempotencyKey);
 const client=initiateDeveloperControlledWalletsClient({apiKey:process.env.CIRCLE_API_KEY,entitySecret:process.env.CIRCLE_ENTITY_SECRET});
 const r=await client.createWalletSet(state.walletSetRequest);
 assert(r.data?.walletSet?.id);
 state.walletSet=r.data.walletSet;state.registered=true;state.registrationVerifiedBy='original idempotent wallet-set request';
 await writeFile(file,JSON.stringify(state,null,2)+'\n',{mode:0o600});
 console.log('Existing secret accepted; original wallet-set request recovered. No secret registration or rotation performed. Preserve any existing Circle recovery file.');
} catch(e) {
 console.log(JSON.stringify({status:'recovery_blocked',httpStatus:e.response?.status??null,circleCode:e.response?.data?.code??null}));
 process.exitCode=2;
} finally {await rm(lock,{recursive:true});}
