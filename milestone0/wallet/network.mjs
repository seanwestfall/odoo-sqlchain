import assert from 'node:assert/strict';
import { decodeEventLog, decodeFunctionData, encodeFunctionData, parseAbi } from 'viem';

export const ARC = Object.freeze({
  chainId: 5042002, network: 'eip155:5042002', rpc: 'https://rpc.testnet.arc.network',
  circleBlockchain: 'ARC-TESTNET', token: '0x3600000000000000000000000000000000000000',
  transferDecimals: 6, feeDecimals: 18,
});
export const AMOUNT_ATOMIC = 10_000n; // 0.01 USDC, ERC-20 interface only.
export const MAX_FEE_ATOMIC = 50_000_000_000_000_000n; // 0.05 USDC, native units.
export const ABI = parseAbi([
  'function decimals() view returns (uint8)',
  'function balanceOf(address) view returns (uint256)',
  'function transfer(address,uint256) returns (bool)',
  'function authorizationState(address,bytes32) view returns (bool)',
  'function DOMAIN_SEPARATOR() view returns (bytes32)',
  'event Transfer(address indexed from,address indexed to,uint256 value)',
]);
export const stringify = data => JSON.stringify(data, (_, value) => typeof value === 'bigint' ? value.toString() : value, 2);
export function calldata(recipient) {
  return encodeFunctionData({ abi: ABI, functionName: 'transfer', args: [recipient, AMOUNT_ATOMIC] });
}
export function validateReceipt({transaction, receipt, block, sender, recipient}) {
  assert.equal(transaction.chainId, ARC.chainId, 'wrong transaction network');
  assert.equal(transaction.from.toLowerCase(), sender.toLowerCase(), 'wrong sender');
  assert.equal(transaction.to?.toLowerCase(), ARC.token.toLowerCase(), 'wrong token');
  assert.equal(transaction.value, 0n, 'native value must be zero for the ERC-20 transfer');
  const decoded = decodeFunctionData({abi: ABI, data: transaction.input});
  assert.equal(decoded.functionName, 'transfer');
  assert.equal(decoded.args[0].toLowerCase(), recipient.toLowerCase());
  assert.equal(decoded.args[1], AMOUNT_ATOMIC);
  assert.equal(receipt.status, 'success', 'receipt reverted');
  assert.equal(receipt.transactionHash.toLowerCase(), transaction.hash.toLowerCase());
  assert.equal(receipt.blockHash.toLowerCase(), block.hash.toLowerCase(), 'block hash mismatch');
  assert.equal(receipt.blockNumber, block.number);
  const transfers = receipt.logs.filter(log => log.address.toLowerCase() === ARC.token.toLowerCase())
    .flatMap(log => {
      try { return [decodeEventLog({abi: ABI, ...log, strict: true})]; } catch { return []; }
    }).filter(event => event.eventName === 'Transfer'
      && event.args.from.toLowerCase() === sender.toLowerCase()
      && event.args.to.toLowerCase() === recipient.toLowerCase()
      && event.args.value === AMOUNT_ATOMIC);
  assert.equal(transfers.length, 1, 'expected exactly one matching six-decimal token Transfer');
  const feeAtomic = receipt.gasUsed * receipt.effectiveGasPrice;
  assert(feeAtomic <= MAX_FEE_ATOMIC, 'actual fee exceeded probe cap');
  return {network: ARC.network, interface: 'erc20', token: ARC.token,
    amountAtomic: AMOUNT_ATOMIC.toString(), amountDecimals: 6,
    feeAtomic: feeAtomic.toString(), feeDecimals: 18,
    transactionHash: receipt.transactionHash, blockHash: receipt.blockHash,
    blockNumber: receipt.blockNumber.toString(), matchingTransferLogs: transfers.length};
}
