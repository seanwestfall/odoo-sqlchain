import assert from 'node:assert/strict';
import { createPublicClient, http, encodeFunctionData, decodeFunctionData, decodeEventLog,
  keccak256, parseTransaction, recoverTransactionAddress, getAddress, zeroAddress } from '../../milestone0/wallet/node_modules/viem/_esm/index.js';
import { initiateDeveloperControlledWalletsClient } from '../../milestone0/wallet/node_modules/@circle-fin/developer-controlled-wallets/dist/developer-controlled-wallets.es.js';
import { ARC, ABI } from '../../milestone0/wallet/network.mjs';

export class ArcError extends Error {
  constructor(code) { super(code); this.code = code; }
}
const integer = value => { assert.match(String(value), /^(0|[1-9][0-9]*)$/); return BigInt(value); };
export function validateSnapshot(s) {
  assert.equal(s.network, ARC.network);
  assert.equal(s.asset, 'USDC');
  assert.equal(s.interface, 'arc-erc20-6-fee18');
  assert(integer(s.amount_atomic) > 0n);
  assert(integer(s.fee_ceiling_atomic) > 0n);
  assert.notEqual(getAddress(s.destination), zeroAddress);
}
export function transactionFor(s, plan) {
  validateSnapshot(s);
  const nonce = integer(plan.nonce);
  assert(nonce <= BigInt(Number.MAX_SAFE_INTEGER));
  assert(integer(plan.gas) * integer(plan.maxFeePerGas) <= integer(s.fee_ceiling_atomic));
  assert(integer(plan.maxPriorityFeePerGas) <= integer(plan.maxFeePerGas));
  return { chainId: ARC.chainId, nonce: Number(nonce), to: ARC.token, value: 0n,
    gas: integer(plan.gas), maxFeePerGas: integer(plan.maxFeePerGas),
    maxPriorityFeePerGas: integer(plan.maxPriorityFeePerGas), type: 'eip1559',
    data: encodeFunctionData({ abi: ABI, functionName: 'transfer', args: [getAddress(s.destination), integer(s.amount_atomic)] }) };
}
export async function validateSigned(s, plan, raw) {
  assert.match(raw, /^0x[0-9a-fA-F]+$/);
  const tx = parseTransaction(raw), expected = transactionFor(s, plan);
  assert.equal(tx.type, 'eip1559');
  for (const key of ['chainId', 'nonce', 'value', 'gas', 'maxFeePerGas', 'maxPriorityFeePerGas']) {
    assert.equal(BigInt(tx[key] ?? 0), BigInt(expected[key]), `signed ${key} differs`);
  }
  assert.equal(tx.to?.toLowerCase(), expected.to.toLowerCase());
  assert.equal(tx.data?.toLowerCase(), expected.data.toLowerCase());
  const sender = await recoverTransactionAddress({ serializedTransaction: raw });
  assert.equal(sender.toLowerCase(), plan.sender.toLowerCase());
  return keccak256(raw);
}
export class ArcAdapter {
  constructor({ rpc, circle, walletId, now = () => new Date() }) {
    this.rpc = rpc; this.circle = circle; this.walletId = walletId; this.now = now;
  }
  async network() {
    if (await this.rpc.getChainId() !== ARC.chainId) throw new ArcError('wrong_network');
    if (await this.rpc.readContract({ address: ARC.token, abi: ABI, functionName: 'decimals' }) !== 6) throw new ArcError('wrong_asset_precision');
  }
  async prepare(s) {
    validateSnapshot(s); await this.network();
    assert.equal(s.source_wallet, this.walletId);
    const wallet = (await this.circle.getWallet({ id: this.walletId })).data?.wallet;
    // Circle's signTransaction endpoint is documented for EVM-TESTNET, not ARC-TESTNET wallets.
    if (wallet?.blockchain !== 'EVM-TESTNET' || wallet.accountType !== 'EOA') throw new ArcError('signing_wallet_required');
    const sender = getAddress(wallet.address);
    assert.notEqual(sender.toLowerCase(), s.destination.toLowerCase());
    const balance = await this.rpc.getBalance({ address: sender });
    if (balance < integer(s.amount_atomic) * 10n ** 12n) throw new ArcError('insufficient_balance');
    const data = encodeFunctionData({ abi: ABI, functionName: 'transfer', args: [getAddress(s.destination), integer(s.amount_atomic)] });
    const gas = (await this.rpc.estimateGas({ account: sender, to: ARC.token, data, value: 0n }) * 120n + 99n) / 100n;
    const maxFeePerGas = (await this.rpc.getGasPrice()) * 2n;
    const maxPriorityFeePerGas = 1_000_000_000n;
    if (maxFeePerGas < maxPriorityFeePerGas || gas * maxFeePerGas > integer(s.fee_ceiling_atomic)) throw new ArcError('fee_ceiling_exceeded');
    if (balance < integer(s.amount_atomic) * 10n ** 12n + gas * maxFeePerGas) throw new ArcError('insufficient_balance');
    const pendingNonce = await this.rpc.getTransactionCount({ address: sender, blockTag: 'pending' });
    return { sender, pendingNonce: String(pendingNonce), gas: String(gas), maxFeePerGas: String(maxFeePerGas), maxPriorityFeePerGas: String(maxPriorityFeePerGas) };
  }
  async sign(s, plan) {
    assert.equal(s.source_wallet, this.walletId);
    const tx = transactionFor(s, plan);
    const transaction = JSON.stringify({ chainId: tx.chainId, nonce: String(tx.nonce), to: tx.to,
      value: '0', gas: String(tx.gas), maxFeePerGas: String(tx.maxFeePerGas),
      maxPriorityFeePerGas: String(tx.maxPriorityFeePerGas), data: tx.data });
    const response = await this.circle.signTransaction({ walletId: this.walletId, transaction, xRequestId: plan.providerRequestId });
    const raw = response.data?.signedTransaction;
    const txHash = await validateSigned(s, plan, raw);
    if (response.data?.txHash) assert.equal(response.data.txHash.toLowerCase(), txHash);
    return { raw, txHash, providerRequestId: plan.providerRequestId, provider: 'circle-sign-transaction' };
  }
  async submit(s, plan, authorization) {
    await this.network();
    const txHash = await validateSigned(s, plan, authorization.raw);
    assert.equal(txHash, authorization.txHash);
    // The caller must persist authorization + dispatch intent before invoking this method.
    try {
      const found = await this.rpc.getTransactionReceipt({ hash: txHash });
      if (found) return { state: 'receipt_available', txHash };
    } catch (error) {
      if (error.name !== 'TransactionReceiptNotFoundError') throw new ArcError('provider_unavailable');
    }
    try {
      const result = await this.rpc.sendRawTransaction({ serializedTransaction: authorization.raw });
      assert.equal(result.toLowerCase(), txHash);
      return { state: 'submitted', txHash };
    } catch {
      // Includes timeout, already-known, nonce-too-low, and rejected broadcast. None prove
      // that an earlier submission did not settle. Never allocate a replacement nonce here.
      return { state: 'uncertain', txHash, reason: 'reconcile_original_hash' };
    }
  }
  async observe(s, plan, authorization) {
    await this.network();
    const hash = await validateSigned(s, plan, authorization.raw);
    let receipt;
    try { receipt = await this.rpc.getTransactionReceipt({ hash }); }
    catch (error) {
      if (error.name === 'TransactionReceiptNotFoundError') return { state: 'uncertain', txHash: hash, observedAt: this.now().toISOString() };
      throw new ArcError('provider_unavailable');
    }
    const block = await this.rpc.getBlock({ blockNumber: receipt.blockNumber });
    const finalized = await this.rpc.getBlock({ blockTag: 'finalized' });
    assert.equal(receipt.transactionHash.toLowerCase(), hash);
    assert.equal(receipt.blockHash.toLowerCase(), block.hash.toLowerCase());
    if (finalized.number < receipt.blockNumber) return { state: 'confirming', txHash: hash, observedAt: this.now().toISOString() };
    // Confirm the finalized block belongs to the same canonical branch as the receipt lookup.
    const canonical = await this.rpc.getBlock({ blockNumber: receipt.blockNumber });
    assert.equal(canonical.hash, receipt.blockHash);
    const feeAtomic = receipt.gasUsed * receipt.effectiveGasPrice;
    assert(feeAtomic <= integer(s.fee_ceiling_atomic));
    let matches = 0;
    if (receipt.status === 'success') {
      matches = receipt.logs.filter(x => x.address.toLowerCase() === ARC.token.toLowerCase()).filter(log => {
        try {
          const e = decodeEventLog({ abi: ABI, ...log, strict: true });
          return e.eventName === 'Transfer' && e.args.from.toLowerCase() === plan.sender.toLowerCase()
            && e.args.to.toLowerCase() === s.destination.toLowerCase() && e.args.value === integer(s.amount_atomic);
        } catch { return false; }
      }).length;
      assert.equal(matches, 1, 'missing or ambiguous token receipt');
    }
    return { state: receipt.status === 'success' ? 'confirmed' : 'reverted', chainId: ARC.chainId,
      network: ARC.network, token: ARC.token, asset: 'USDC', amountAtomic: s.amount_atomic, amountDecimals: 6,
      feeAtomic: String(feeAtomic), feeDecimals: 18, txHash: hash, receiptStatus: receipt.status,
      blockNumber: String(receipt.blockNumber), blockHash: receipt.blockHash,
      finalizedBlockNumber: String(finalized.number), finalizedBlockHash: finalized.hash,
      finality: 'canonical receipt at or below RPC finalized block; Arc deterministic finality',
      observedAt: this.now().toISOString(), matchingTransferLogs: matches, providerRequestId: plan.providerRequestId };
  }
  async reconcile(s, plan, authorization) { return this.observe(s, plan, authorization); }
}
export function configuredAdapter(env = process.env) {
  if (!env.CIRCLE_API_KEY?.startsWith('TEST_API_KEY:') || !env.CIRCLE_ENTITY_SECRET || !env.CIRCLE_SIGNING_WALLET_ID) throw new ArcError('circle_configuration_required');
  return new ArcAdapter({ rpc: createPublicClient({ transport: http(ARC.rpc, { retryCount: 0, timeout: 20000 }) }),
    circle: initiateDeveloperControlledWalletsClient({ apiKey: env.CIRCLE_API_KEY, entitySecret: env.CIRCLE_ENTITY_SECRET }), walletId: env.CIRCLE_SIGNING_WALLET_ID });
}
