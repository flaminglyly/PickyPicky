// Local JSON-over-stdin bridge. Never log signed URLs or content keys.
const fs = require('node:fs');
const axios = require('axios');
const {evidence,route}=require('./response_diagnostics.cjs');
const {fetchAppPlayUrl,requestJson} = require('./vendor/jackotom/app-source');
const {decryptMp4Buffer} = require('./vendor/zhenyong97/media');
let count=0, duration=null;
const traces=[];
axios.interceptors.request.use(async config => {
  if (++count>2) throw Object.assign(Error('请求数量超出单集预算'),{code:'REQUEST_BUDGET'});
  const u=new URL(config.url);
  if (u.protocol!=='https:' || u.username || u.password || !['fqnovel.com','snssdk.com'].some(d=>u.hostname===d||u.hostname.endsWith('.'+d)))
    throw Object.assign(Error('取址域名不受支持'),{code:'SECURITY_BLOCKED'});
  if(count>1) await new Promise(r=>setTimeout(r,3000));
  config._diagnosticStart=Date.now();
  return config;
});
axios.interceptors.response.use(response => {
  const raw=typeof response.data==='string'?response.data:'';
  let responseFormat='non-json';
  if(typeof response.data==='string'&&!raw)responseFormat='empty';
  else try{const parsed=raw?JSON.parse(raw):response.data;responseFormat=parsed&&typeof parsed==='object'?'json':'json-scalar';}catch{}
  traces.push({host:new URL(response.config.url).hostname,status:response.status,
    contentType:String(response.headers['content-type']||'').split(';')[0].slice(0,80),
    bodyBytes:Buffer.byteLength(raw),responseFormat,...evidence(response)});
  try {
    const data=typeof response.data==='string'?JSON.parse(response.data):response.data;
    const d=Number(data?.video_info?.data?.video_duration ?? data?.video_info?.data?.duration);
    if(Number.isFinite(d)&&d>0) duration=d;
  }catch {}
  return response;
},error=>{
  const config=error.config||{};
  let host;try{host=new URL(config.url).hostname;}catch{}
  traces.push({host,...route(config),diagnosis:'transport_error_source_unknown',certainty:'unknown',
    code:/^[A-Z0-9_]{1,40}$/.test(error.code||'')?error.code:'NETWORK_ERROR',
    elapsedMs:config._diagnosticStart?Date.now()-config._diagnosticStart:undefined});
  return Promise.reject(error);
});
async function run(job) {
  if(job.action==='register') return {identity:await require('./vendor/jackotom/playback-device').getPlaybackDevice(requestJson)};
  if(job.action==='resolve') {
    if(!/^[0-9]{1,30}$/.test(job.episodeId)) throw Error('分集 ID 格式异常');
    const media=await fetchAppPlayUrl(job.episodeId,{quality:'auto',identity:job.identity});
    if(media.vid!==job.episodeId) throw Error('App 返回的分集 ID 不匹配');
    return {media,duration:media.duration || duration};
  }
  if(job.action==='decode') {
    if(!/^[0-9a-f]{32}$/i.test(job.key||''))throw Error('媒体密钥格式异常');
    const data=fs.readFileSync(job.input);
    const decoded=decryptMp4Buffer(data,Buffer.from(job.key,'hex'));
    fs.writeFileSync(job.output,decoded,{flag:'wx'});
    return {bytes:decoded.length};
  }
  throw Error('未知媒体操作');
}
if(require.main===module) {
  let input='';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data',chunk=>{input+=chunk;if(input.length>1000000)process.exit(1);});
  process.stdin.on('end',async()=>{
    try {process.stdout.write(JSON.stringify({ok:true,...await run(JSON.parse(input)),traces}));}
    catch(error) {
      const safe=['DEVICE_REGISTRATION_FAILED','SECURITY_BLOCKED','EMPTY_RESPONSE','INVALID_RESPONSE','MISSING_MODEL','BUSINESS_REJECTED','REQUEST_BUDGET','ETIMEDOUT','ENOTFOUND','ECONNRESET'].includes(error.code)?error.code:'APP_MEDIA_FAILED';
      // Messages from the audited module are generic; strip any accidental URL.
      const message=String(error.message||'App 媒体操作失败').replace(/https?:\/\/\S+/g,'[地址已隐藏]').slice(0,200);
      process.stdout.write(JSON.stringify({ok:false,error:message,code:safe,status:error.status,retryAfter:error.retryAfter,traces}));
    }
  });
}
module.exports={run};
