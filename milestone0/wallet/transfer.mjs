// One bounded compatibility transfer; not a production payment worker.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdir, open, readFile, rename, rm } from 'node:fs/promises';
import { initiateDeveloperControlledWalletsClient } from '@circle-fin/developer-controlled-wallets';
import { createPublicClient, http, getAddress, formatUnits, zeroAddress } from 'viem';
import { ARC, ABI, AMOUNT_ATOMIC, MAX_FEE_ATOMIC, calldata, stringify, validateReceipt } from './network.mjs';

const root = new URL('../../.local/milestone0/', import.meta.url);
const journalFile = new URL('circle-transfer.json', root);
const lock = new URL('circle-transfer.lock/', root);
const mode = process.argv[2] ?? '--plan';
assert(['--plan', '--submit', '--observe'].includes(mode), 'Use --plan, --submit, or --observe');
const required = ['CIRCLE_API_KEY','CIRCLE_ENTITY_SECRET','CIRCLE_WALLET_ID','CIRCLE_RECIPIENT'];
const missing = required.filter(key => !process.env[key]);
if (missing.length) {
  console.error(`BLOCKED: configure ${missing.join(', ')} in .local/milestone0/circle.env. Do not paste secrets into chat.`);
  process.exit(2);
}
assert(process.env.CIRCLE_API_KEY.startsWith('TEST_API_KEY:'), 'Only Circle TEST_API_KEY credentials accepted');
const recipient = getAddress(process.env.CIRCLE_RECIPIENT);
assert.notEqual(recipient, zeroAddress);
const client = initiateDeveloperControlledWalletsClient({
  apiKey: process.env.CIRCLE_API_KEY, entitySecret: process.env.CIRCLE_ENTITY_SECRET,
});
const rpc = createPublicClient({transport: http(ARC.rpc, {timeout: 30_000, retryCount: 0})});
async function persist(value) {
  const temporary = new URL('circle-transfer.tmp', root);
  const handle = await open(temporary, 'w', 0o600);
  try { await handle.writeFile(stringify(value) + '\n'); await handle.sync(); } finally { await handle.close(); }
  await rename(temporary, journalFile);
}
async function balance(address, blockNumber) {
  return {nativeAtomic: await rpc.getBalance({address, blockNumber}),
    erc20Atomic: await rpc.readContract({address: ARC.token, abi: ABI, functionName:'balanceOf', args:[address], blockNumber})};
}
await mkdir(root, {recursive: true, mode: 0o700});
// An interrupted process may leave this lock. Inspect the journal before removing it.
await mkdir(lock);
try {
  assert.equal(await rpc.getChainId(), ARC.chainId);
  assert.equal(await rpc.readContract({address: ARC.token, abi: ABI, functionName: 'decimals'}), 6);
  const wallet = (await client.getWallet({id: process.env.CIRCLE_WALLET_ID})).data?.wallet;
  assert(wallet && wallet.blockchain === ARC.circleBlockchain && wallet.accountType === 'EOA', 'An Arc-testnet EOA wallet is required');
  const sender = getAddress(wallet.address);
  assert.notEqual(sender, recipient, 'Use a distinct test recipient');
  let journal;
  try { journal = JSON.parse(await readFile(journalFile, 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (journal) {
    assert.equal(journal.sender, sender); assert.equal(journal.recipient, recipient);
    assert.equal(journal.walletId, wallet.id); assert.equal(journal.network, ARC.network);
    assert.equal(journal.amountAtomic, AMOUNT_ATOMIC.toString());
    if (journal.stage === 'complete') {
      console.log('This probe already completed. Existing evidence retained; no second transfer sent.');
      process.exitCode = 0;
    } else if (journal.stage === 'submitting' && !journal.circleTransactionId) {
      throw new Error('Submission outcome uncertain. Reconcile the saved idempotency key/refId in Circle before retrying; do not delete the journal.');
    }
  }
  if (journal?.stage !== 'complete') {
    if (!journal?.circleTransactionId) {
      assert.notEqual(mode, '--observe', 'No submitted Circle transaction is recorded');
      const gas = await rpc.estimateGas({account:sender, to:ARC.token, data:calldata(recipient), value:0n});
      const gasLimit = (gas * 120n + 99n) / 100n;
      const maxFeePerGas = (await rpc.getGasPrice()) * 2n;
      const priorityFee = 1_000_000_000n;
      assert(maxFeePerGas >= priorityFee);
      const feeBound = gasLimit * maxFeePerGas;
      assert(feeBound <= MAX_FEE_ATOMIC, 'Estimated fee cap exceeds 0.05 test USDC; no submission');
      const block = await rpc.getBlockNumber();
      const before = {blockNumber:block, sender:await balance(sender,block), recipient:await balance(recipient,block)};
      assert(before.sender.nativeAtomic >= AMOUNT_ATOMIC * 10n**12n + feeBound, 'Insufficient test USDC for transfer plus capped gas');
      const request = {walletId:wallet.id, contractAddress:ARC.token, callData:calldata(recipient), amount:'0',
        idempotencyKey:randomUUID(), refId:'chainsql-milestone0-arc-probe',
        fee:{type:'absolute', config:{gasLimit:gasLimit.toString(), maxFee:formatUnits(maxFeePerGas,9), priorityFee:formatUnits(priorityFee,9)}}};
      journal = {stage:'planned', createdAt:new Date().toISOString(), network:ARC.network,
        walletId:wallet.id, sender, recipient, amountAtomic:AMOUNT_ATOMIC.toString(), amountDecimals:6,
        maxFeeAtomic:feeBound.toString(), feeDecimals:18, before, request};
      if (mode === '--plan') {
        console.log(stringify(journal));
      } else {
        journal.stage = 'submitting';
        await persist(journal); // Save the exact request before any remote side effect.
        const submitted = (await client.createContractExecutionTransaction(request)).data;
        assert(submitted?.id, 'No Circle transaction ID returned; reconcile the saved request');
        journal.circleTransactionId = submitted.id;
        journal.stage = 'submitted';
        await persist(journal);
      }
    }
    if (journal.circleTransactionId) {
      const deadline = Date.now() + 180_000;
      let observed;
      while (Date.now() < deadline) {
        observed = (await client.getTransaction({id:journal.circleTransactionId})).data?.transaction;
        if (observed?.state === 'COMPLETE') break;
        if (['FAILED','CANCELLED','DENIED'].includes(observed?.state)) throw new Error(`Circle transaction ended ${observed.state}; see saved ID`);
        await new Promise(resolve => setTimeout(resolve,3000));
      }
      assert(observed?.state === 'COMPLETE' && observed.txHash, 'Circle outcome pending; rerun --observe using the same journal');
      assert.equal(observed.blockchain, ARC.circleBlockchain);
      const receipt = await rpc.getTransactionReceipt({hash:observed.txHash});
      const transaction = await rpc.getTransaction({hash:observed.txHash});
      const block = await rpc.getBlock({blockNumber:receipt.blockNumber});
      const finalized = await rpc.getBlock({blockTag:'finalized'});
      assert(finalized.number >= receipt.blockNumber, 'Receipt block not yet finalized');
      const verified = validateReceipt({transaction,receipt,block,sender,recipient});
      const evidence = {...verified, observedAt:new Date().toISOString(),
        circleTransactionId:journal.circleTransactionId, circleState:observed.state,
        walletPath:'Circle developer-controlled EOA / contract execution',
        before:journal.before, after:{blockNumber:receipt.blockNumber,
          sender:await balance(sender,receipt.blockNumber), recipient:await balance(recipient,receipt.blockNumber)},
        transaction,receipt,finalizedBlockNumber:finalized.number};
      await writeEvidence(evidence);
      journal.stage = 'complete'; journal.evidence = verified; await persist(journal);
      console.log(stringify(verified));
    }
  }
} catch (error) {
  // Do not dump SDK errors: request objects may contain credentials/ciphertexts.
  console.error(error.name === 'AssertionError' ? error.message : `Probe stopped (${error.code ?? error.name}). Inspect local journal and Circle transaction status before retrying.`);
  process.exitCode = 1;
} finally { await rm(lock, {recursive:true}); }
async function writeEvidence(value) {
  const file = new URL('../evidence/arc-transfer.json', import.meta.url);
  const handle = await open(file, 'w', 0o600);
  try { await handle.writeFile(stringify(value) + '\n'); await handle.sync(); } finally { await handle.close(); }
}
