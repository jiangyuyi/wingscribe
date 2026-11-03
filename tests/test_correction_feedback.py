"""Exercise the actual modal submission code while its request is pending."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_correction_feedback_success_failure_and_duplicate_clicks():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for modal JavaScript checks')
    page = Path(__file__).resolve().parents[1] / 'src/web/templates/index.html'
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8');
const code=html.slice(html.indexOf('        let correctionBusy'),html.indexOf('        // Initial load'));
async function scenario(failure){
 let resolve,reject,requests=0,reloaded=0,hidden=0,alerts=0;
 const body={},close={},progress={style:{},focus(){}},handlers={};
 const dialog={setAttribute(){},querySelector:s=>s==='.modal-body'?body:close,
  addEventListener:(n,fn)=>handlers[n]=fn,contains:()=>false};
 const pending=new Promise((a,b)=>{resolve=a;reject=b;});
 const context={document:{getElementById:id=>id==='editModal'?dialog:progress},window:{},
  currentPhotoId:1,confirm:()=>true,alert:()=>alerts++,
  fetch:()=>{requests++;return pending;},editModal:{hide:()=>hidden++},location:{reload:()=>reloaded++}};
 vm.runInNewContext(code,context);
 const request=context.window.selectSpecies('species','Bird');
 assert.equal(progress.hidden,false);assert.equal(body.inert,true);assert.equal(close.disabled,true);
 await context.window.selectSpecies('species','Bird');assert.equal(requests,1);
 let blocked=false;handlers['hide.bs.modal']({preventDefault(){blocked=true;}});assert(blocked);
 if(failure)reject(new Error('connection lost'));else resolve({ok:true,json:async()=>({status:'success'})});
 await request;
 assert.equal(body.inert,false);assert.equal(close.disabled,false);assert.equal(progress.hidden,true);
 assert.equal(hidden,failure?0:1);assert.equal(reloaded,failure?0:1);assert.equal(alerts,failure?1:0);
}
(async()=>{await scenario(false);await scenario(true);})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    subprocess.run([node, '-e', script, str(page)], check=True, capture_output=True, timeout=20)
