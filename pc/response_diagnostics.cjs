// Evidence only: never store credentials, signed URLs, raw bodies or arbitrary headers.
const {createHash}=require('node:crypto');
const {getProxyForUrl}=require('proxy-from-env');
function token(value){const s=String(value??'');return /^[a-zA-Z0-9_.:\- /;,=]{1,160}$/.test(s)?s:undefined;}
function route(config){
 let proxy;
 if(config.proxy===false)return {proxyMode:'disabled'};
 if(config.proxy&&typeof config.proxy==='object')return {proxyMode:'explicit',proxyHost:token(config.proxy.host),proxyPort:token(config.proxy.port)};
 try{proxy=getProxyForUrl(config.url);}catch{}
 if(!proxy)return {proxyMode:'direct'};
 try{const u=new URL(proxy);return {proxyMode:'environment',proxyHost:u.hostname,proxyPort:u.port|| (u.protocol==='https:'?'443':'80')};}catch{return {proxyMode:'invalid'};}
}
function evidence(response){
 const h=response.headers||{},socket=response.request?.socket;
 const raw=typeof response.data==='string'?response.data:'';
 const headers={};
 for(const key of ['content-length','content-type','content-encoding','server','via','x-cache','retry-after','x-request-id','x-tt-logid','x-tt-trace-id','cf-ray','cf-mitigated']){
  const value=token(h[key]);if(value!==undefined)headers[key]=value;
 }
 let diagnosis='undetermined',certainty='unknown';
 if(response.status===407){diagnosis='proxy_authentication_required';certainty='explicit_http_status';}
 else if(String(h['cf-mitigated']).toLowerCase()==='challenge'){diagnosis='edge_security_challenge';certainty='explicit_response_header';}
 else if(response.status===429){diagnosis='rate_limit_reported_source_unknown';certainty='explicit_http_status';}
 else if(response.status>=500){diagnosis='server_or_gateway_error_source_unknown';certainty='explicit_http_status';}
 else if(response.status===200&&!raw.trim()){diagnosis='empty_response_source_unknown';}
 else if(response.status===403){diagnosis='access_denied_reason_unknown';certainty='explicit_http_status';}
 let cert;try{cert=socket?.getPeerCertificate?.();}catch{}
 return {...route(response.config),responseHeaders:headers,diagnosis,certainty,
  peerAddress:socket?.remoteAddress,peerPort:socket?.remotePort,
  tlsAuthorized:socket?.encrypted?socket.authorized:undefined,
  tlsPeerFingerprint:token(cert?.fingerprint256),
  responseComplete:response.request?.res?.complete,
  bodySha256:createHash('sha256').update(raw).digest('hex'),
  elapsedMs:response.config._diagnosticStart?Date.now()-response.config._diagnosticStart:undefined};
}
module.exports={evidence,route};
