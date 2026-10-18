// Read-only: no credentials, signatures, /verify, /settle, or transactions.
import { writeFile } from 'node:fs/promises';
import { encodeFunctionData, zeroAddress, zeroHash } from 'viem';
import { baseSepolia } from 'viem/chains';
import { ARC, ABI, stringify } from './network.mjs';

const observedAt = new Date().toISOString();
const facilitatorUrl = 'https://x402.org/facilitator';
async function json(url, options = {}) {
  const response = await fetch(url, {...options, signal: AbortSignal.timeout(30_000)});
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}
async function probe(rpc, token) {
  const requests = [
    ['eth_chainId', []], ['eth_blockNumber', []], ['eth_gasPrice', []],
    ['eth_call', [{to: token, data: encodeFunctionData({abi: ABI, functionName: 'decimals'})}, 'latest']],
    ['eth_call', [{to: token, data: encodeFunctionData({abi: ABI, functionName: 'authorizationState', args: [zeroAddress, zeroHash]})}, 'latest']],
    ['eth_call', [{to: token, data: encodeFunctionData({abi: ABI, functionName: 'DOMAIN_SEPARATOR'})}, 'latest']],
    ['eth_getBlockByNumber', ['finalized', false]],
  ].map(([method, params], i) => ({jsonrpc: '2.0', id: i + 1, method, params}));
  const response = await json(rpc, {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(requests)});
  return {rpc, token, requests, response};
}
const [supported, arc, base] = await Promise.all([
  json(`${facilitatorUrl}/supported`), probe(ARC.rpc, ARC.token),
  probe(baseSepolia.rpcUrls.default.http[0], '0x036CbD53842c5426634e7929541eC2318f3dCF7e'),
]);
function rpcValue(response, id) {
  const value = response.find(r => r.id === id);
  if (!value || value.error) throw new Error(`Required RPC check ${id} failed`);
  return value.result;
}
if (Number(BigInt(rpcValue(arc.response, 1))) !== ARC.chainId) throw new Error('Arc chain mismatch');
if (BigInt(rpcValue(arc.response, 4)) !== 6n) throw new Error('Arc decimals mismatch');
if (BigInt(rpcValue(base.response, 1)) !== 84532n) throw new Error('Base Sepolia chain mismatch');
if (BigInt(rpcValue(base.response, 4)) !== 6n) throw new Error('Base USDC decimals mismatch');
const advertised = network => supported.kinds.some(k => k.x402Version === 2 && k.scheme === 'exact' && k.network === network);
const result = {observedAt, facilitatorUrl, supported, arc, base,
  findings: {arcExactV2Advertised: advertised(ARC.network), baseSepoliaExactV2Advertised: advertised('eip155:84532'),
    merchant: null, settlementTested: false, circleTransferTested: false,
    note: 'Read-only method probes do not prove successful EIP-3009 settlement. No merchant or signing wallet configured.'}};
await writeFile(new URL('../evidence/network-probe.json', import.meta.url), stringify(result) + '\n');
console.log(stringify({observedAt, ...result.findings}));
