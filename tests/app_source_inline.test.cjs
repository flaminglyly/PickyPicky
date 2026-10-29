const test=require('node:test'),assert=require('node:assert/strict');
let calls=[],payload;
const axios=async config=>{calls.push(config);return {status:200,headers:{},data:JSON.stringify(payload)}};
const path=require.resolve('../pc/node_modules/axios');require.cache[path]={id:path,filename:path,loaded:true,exports:axios};
const {fetchAppPlayUrl}=require('../pc/vendor/jackotom/app-source');
const identity={device_id:'1234567890123456789',iid:'9876543210987654321',cdid:'test'};
function model(encrypt=false){return {video_duration:75.651,video_list:[{main_url:'https://test.qznovelvod.com/video.mp4',codec_type:'hevc',definition:'1080p',vwidth:1080,vheight:1920,encrypt_info:{encrypt}}]}}
test('direct model uses registered identity, no fallback request',async()=>{
 calls=[];payload={code:0,data:{123:{video_model:JSON.stringify(model())}}};
 const media=await fetchAppPlayUrl('123',{identity});
 assert.equal(media.vid,'123');assert.equal(media.duration,75.651);assert.equal(calls.length,1);
 assert.equal(new URL(calls[0].url).searchParams.get('device_id'),identity.device_id);
 assert.equal(calls[0].headers['x-medusa'],undefined);
});
test('does not borrow model from a different episode',async()=>{
 payload={data:{456:{video_model:model()}}};await assert.rejects(fetchAppPlayUrl('123',{identity}),e=>e.code==='MISSING_MODEL');
});
test('encrypted direct model without key is rejected',async()=>{
 payload={data:{123:{video_model:model(true)}}};await assert.rejects(fetchAppPlayUrl('123',{identity}),e=>e.code==='INVALID_RESPONSE');
});
