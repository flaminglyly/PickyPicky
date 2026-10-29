const test=require('node:test');
const assert=require('node:assert/strict');
const requestHandlers=[],responseHandlers=[];
let status=200;
const axios=async config=>{
 for(const handle of requestHandlers)config=await handle(config);
 let response={status,data:'',config,headers:{'content-type':'application/json','retry-after':'600'}};
 for(const handle of responseHandlers)response=await handle(response);
 return response;
};
axios.interceptors={request:{use:cb=>requestHandlers.push(cb)},response:{use:cb=>responseHandlers.push(cb)}};
const axiosPath=require.resolve('../pc/node_modules/axios');
require.cache[axiosPath]={id:axiosPath,filename:axiosPath,loaded:true,exports:axios};
const worker=require('../pc/app-worker.cjs');
test('empty HTTP 200 preserves EMPTY_RESPONSE and status',async()=>{
 await assert.rejects(worker.run({action:'resolve',episodeId:'123',identity:{device_id:'12345',iid:'67890',cdid:'test'}}),error=>error.code==='EMPTY_RESPONSE'&&error.status===200);
});
test('HTTP 429 and Retry-After survive response interceptor',async()=>{
 status=429;
 await assert.rejects(worker.run({action:'resolve',episodeId:'123',identity:{device_id:'12345',iid:'67890',cdid:'test'}}),error=>error.status===429&&error.retryAfter==='600');
});
