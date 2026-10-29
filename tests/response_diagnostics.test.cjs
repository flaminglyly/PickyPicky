const test=require('node:test'),assert=require('node:assert/strict');
const {evidence}=require('../pc/response_diagnostics.cjs');
const response=(status,headers={},data='')=>({status,headers,data,config:{url:'https://example.com/api?token=SECRET',proxy:false}});
test('empty and 403 never imply risk control or proxy fault',()=>{
 assert.equal(evidence(response(200)).diagnosis,'empty_response_source_unknown');
 assert.equal(evidence(response(403)).diagnosis,'access_denied_reason_unknown');
});
test('explicit status and security marker classified separately',()=>{
 assert.equal(evidence(response(407)).diagnosis,'proxy_authentication_required');
 assert.equal(evidence(response(429)).diagnosis,'rate_limit_reported_source_unknown');
 assert.equal(evidence(response(200,{'cf-mitigated':'challenge'})).diagnosis,'edge_security_challenge');
 assert.equal(evidence(response(502)).diagnosis,'server_or_gateway_error_source_unknown');
});
test('secrets are not retained and response IDs remain',()=>{
 const r=response(200,{'set-cookie':'SECRET','location':'https://example.com/?secret=SECRET','x-request-id':'request-123','server':'https://bad/?secret=SECRET'},'SECRET');
 r.config.proxy={host:'localhost',port:7890,auth:{username:'SECRET',password:'SECRET'}};
 const e=evidence(r);assert.ok(!JSON.stringify(e).includes('SECRET'));
 assert.equal(e.responseHeaders['x-request-id'],'request-123');assert.equal(e.proxyMode,'explicit');
});
test('transport evidence records observed peer separately from proxy configuration',()=>{
 const r=response(200);r.request={socket:{remoteAddress:'127.0.0.1',remotePort:7890},res:{complete:true}};
 const e=evidence(r);assert.equal(e.peerAddress,'127.0.0.1');assert.equal(e.responseComplete,true);assert.equal(e.diagnosis,'empty_response_source_unknown');
});
