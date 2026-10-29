const test=require('node:test'),assert=require('node:assert/strict');
function fresh(){const p=require.resolve('../pc/vendor/jackotom/playback-device');delete require.cache[p];return require(p).getPlaybackDevice;}
test('registration shares one request, preserves string IDs, discards tokens',async()=>{
 const get=fresh();let n=0;
 const request=async(url,options)=>{n++;assert.ok(url.startsWith('https://log5-applog-lf.fqnovel.com/service/2/device_register/'));assert.ok(Buffer.isBuffer(options.data));return {device_id_str:'1234567890123456789',install_id_str:'9876543210987654321',device_token:'not-to-retain'};};
 const devices=await Promise.all(Array.from({length:5},()=>get(request)));
 assert.equal(n,1);assert.equal(devices[0].device_id,'1234567890123456789');assert.equal(devices[0].device_token,undefined);
});
test('registration preserves rate limit and caches failure',async()=>{
 const get=fresh();let n=0;const error=Object.assign(Error('limited'),{status:429,retryAfter:'600'});
 const request=async()=>{n++;throw error;};
 for(let i=0;i<2;i++)await assert.rejects(get(request),e=>e.status===429&&e.retryAfter==='600');
 assert.equal(n,1);
});
test('registration rejects imprecise numerical IDs',async()=>{
 await assert.rejects(fresh()(async()=>({device_id:1234567890123456789,install_id:456})),e=>e.code==='DEVICE_REGISTRATION_FAILED');
});
