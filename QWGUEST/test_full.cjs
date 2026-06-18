const http = require('http');

function getStatus() {
  return new Promise((resolve) => {
    const req = http.request({hostname:'127.0.0.1',port:3264,path:'/api/status',method:'GET'}, (res) => {
      let body='';
      res.on('data',c=>body+=c);
      res.on('end',()=>resolve({status:res.statusCode,body}));
    });
    req.on('error',()=>resolve({status:0,body:'no connection'}));
    req.setTimeout(5000,()=>{req.destroy();resolve({status:0,body:'timeout'});});
    req.end();
  });
}

async function main() {
  console.log('Before POST:', await getStatus());
  
  const data = JSON.stringify({model:'qwen-max-latest',messages:[{role:'user',content':'Hi'}],stream:false,max_tokens:10});
  const req = http.request({hostname:'127.0.0.1',port:3264,path:'/api/chat/completions',method:'POST',headers:{'Authorization':'Bearer test','Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}}, (res) => {
    let body='';
    res.on('data',c=>body+=c);
    res.on('end',()=>{
      console.log('POST response:', res.statusCode, body.substring(0,200));
      setTimeout(async () => {
        console.log('After POST:', await getStatus());
        process.exit(0);
      }, 1000);
    });
  });
  req.on('error',(e)=>{
    console.log('POST error:', e.message);
    setTimeout(async () => {
      console.log('After POST:', await getStatus());
      process.exit(0);
    }, 1000);
  });
  req.setTimeout(30000,()=>{req.destroy();console.log('POST timeout');setTimeout(async()=>{console.log('After POST:',await getStatus());process.exit(0);},1000);});
  req.write(data);
  req.end();
}

main();
