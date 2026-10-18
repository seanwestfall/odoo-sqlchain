// Create only the milestone's Circle testnet configuration. Never rotate an existing secret.
import assert from 'node:assert/strict';
import { randomBytes, randomUUID, createHash } from 'node:crypto';
import { mkdir, open, readFile, rename, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { initiateDeveloperControlledWalletsClient, registerEntitySecretCiphertext } from '@circle-fin/developer-controlled-wallets';
import { stringify, ARC } from './network.mjs';

process.umask(0o077);
const root = new URL('../../.local/milestone0/', import.meta.url);
const envFile = new URL('circle.env', root);
const stateFile = new URL('circle-setup.json', root);
const lock = new URL('circle-setup.lock/', root);
const key = process.env.CIRCLE_API_KEY ?? '';
if (!key.startsWith('TEST_API_KEY:')) {
  console.error(key.startsWith('TEST_CLIENT_KEY:')
    ? 'BLOCKED: the saved key is a test client key. Replace it with a server key beginning TEST_API_KEY: in circle.env.'
    : 'BLOCKED: a Circle server TEST_API_KEY is required in circle.env. No setup request sent.');
  process.exit(2);
}
await mkdir(root, {recursive:true, mode:0o700});
await mkdir(lock);
async function writePrivate(file, data) {
  const temporary = new URL(file.href + '.tmp');
  const h = await open(temporary, 'w', 0o600);
  try { await h.writeFile(data); await h.sync(); } finally { await h.close(); }
  await rename(temporary,file);
}
async function saveEnv(values) {
  let text = await readFile(envFile,'utf8');
  for (const [name,value] of Object.entries(values)) {
    const line = `${name}=${JSON.stringify(value)}`;
    const regex = new RegExp(`^${name}=.*$`,'m');
    text = regex.test(text) ? text.replace(regex,()=>line) : text + '\n' + line + '\n';
  }
  await writePrivate(envFile,text);
}
try {
  // Validate server authentication before generating or registering anything.
  const auth = await fetch('https://api.circle.com/v1/w3s/wallets?pageSize=1', {
    headers:{Authorization:`Bearer ${key}`},signal:AbortSignal.timeout(30_000),
  });
  assert(auth.ok, `Circle server API authentication failed: HTTP ${auth.status}`);
  let state;
  try { state=JSON.parse(await readFile(stateFile,'utf8')); }
  catch(error) { if(error.code!=='ENOENT') throw error; }
  const fingerprint = createHash('sha256').update(key).digest('hex');
  state ??= {createdAt:new Date().toISOString(),keyFingerprint:fingerprint,
    walletSetRequest:{name:'ChainSQL milestone 0 (test only)',idempotencyKey:randomUUID()},
    walletRequestKey:randomUUID()};
  assert.equal(state.keyFingerprint,fingerprint,'API key changed: reconcile the existing setup journal before continuing');
  let secret = process.env.CIRCLE_ENTITY_SECRET;
  if (!secret) {
    assert(!state.registrationStarted,'Registration was attempted previously; recover the saved secret rather than generate another');
    secret = randomBytes(32).toString('hex');
    await saveEnv({CIRCLE_ENTITY_SECRET:secret});
  }
  assert(/^[a-fA-F0-9]{64}$/.test(secret),'Entity secret must contain exactly 32 random bytes in hexadecimal');
  if (!state.registered) {
    assert(!state.registrationStarted,'Registration outcome is unresolved. Inspect Circle Console and the recovery directory before any retry; do not rotate the secret');
    state.registrationStarted=true;
    await writePrivate(stateFile,stringify(state)+'\n');
    const recovery = new URL('circle-recovery/',root);
    await mkdir(recovery,{recursive:true,mode:0o700});
    const response = await registerEntitySecretCiphertext({apiKey:key,entitySecret:secret,
      recoveryFileDownloadPath:fileURLToPath(recovery)});
    assert(response.data?.recoveryFile,'Registration returned no recovery file; stop and contact Circle support');
    // Explicit private copy even if the SDK's optional download helper fails.
    await writePrivate(new URL('entity-secret-recovery.dat',recovery),response.data.recoveryFile);
    state.registered=true;
    await writePrivate(stateFile,stringify(state)+'\n');
  }
  const client=initiateDeveloperControlledWalletsClient({apiKey:key,entitySecret:secret});
  if(!state.walletSet) {
    const response=await client.createWalletSet(state.walletSetRequest);
    assert(response.data?.walletSet?.id,'Missing wallet set ID');
    state.walletSet=response.data.walletSet;
    await writePrivate(stateFile,stringify(state)+'\n');
  }
  if(!state.wallets) {
    const response=await client.createWallets({walletSetId:state.walletSet.id,
      blockchains:[ARC.circleBlockchain],count:2,accountType:'EOA',idempotencyKey:state.walletRequestKey});
    assert.equal(response.data?.wallets?.length,2,'Expected two wallets');
    state.wallets=response.data.wallets;
    await writePrivate(stateFile,stringify(state)+'\n');
  }
  const [source,destination]=state.wallets;
  assert(source.blockchain===ARC.circleBlockchain && destination.blockchain===ARC.circleBlockchain);
  assert.notEqual(source.address.toLowerCase(),destination.address.toLowerCase());
  await saveEnv({CIRCLE_WALLET_ID:source.id,CIRCLE_RECIPIENT:destination.address});
  console.log(stringify({status:'ready_for_testnet_funding',blockchain:ARC.circleBlockchain,
    sender:source.address,recipient:destination.address,
    recoveryDirectory:fileURLToPath(new URL('circle-recovery/',root))}));
} catch(error) {
  console.error(error.name==='AssertionError' ? error.message
    : `Circle setup stopped (${error.code ?? error.name}). Secret and journal remain private on disk; no rotation attempted.`);
  process.exitCode=1;
} finally { await rm(lock,{recursive:true}); }
