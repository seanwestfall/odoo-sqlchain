import {configuredAdapter} from '../../chainsql/arc/adapter.mjs';
const a=configuredAdapter();
try {
 const w=(await a.circle.getWallet({id:a.walletId})).data?.wallet;
 const b=await a.rpc.getBalance({address:w.address});
 console.log(JSON.stringify({walletId:w.id,blockchain:w.blockchain,address:w.address,balanceAtomic18:String(b)}));
} catch(e) {console.log(JSON.stringify({errorName:e.name,httpStatus:e.response?.status??null,circleCode:e.response?.data?.code??null}));}
