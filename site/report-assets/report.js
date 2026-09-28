(async()=>{
  const labels={pending:'待核验',ready:'实际核验完成',partial:'部分完成',failed:'实际失败',not_deployed:'未部署',historical_verified:'历史实测'};
  const localURL=value=>{
    if(typeof value!=='string'||!value||value.startsWith('/')||value.includes('..'))return null;
    try{const u=new URL(value,location.href);return u.origin===location.origin&&u.protocol===location.protocol?u.href:null}catch{return null}
  };
  const evidenceURL=value=>{
    if(typeof value!=='string')return null;
    const local=localURL(value);if(local)return local;
    try{const u=new URL(value);return u.protocol==='https:'&&['github.com','dingyucanada.github.io'].includes(u.hostname)&&!u.username&&!u.password?u.href:null}catch{return null}
  };
  try{
    const response=await fetch('report-assets/deployment-status.json',{cache:'no-store'});
    if(!response.ok)return;
    const data=await response.json();
    const audit=data.deployment_audit;
    if(audit&&typeof audit==='object'&&labels[audit.state]){
      const container=document.querySelector('[data-deployment-state]');
      if(container)container.dataset.deploymentState=audit.state;
      const summary=document.querySelector('[data-deployment-summary]');
      if(summary&&typeof audit.summary==='string')summary.textContent=audit.summary;
      const list=document.querySelector('[data-deployment-components]');
      if(list&&Array.isArray(audit.components)&&audit.components.length){
        const nodes=[];
        for(const item of audit.components.slice(0,20)){
          if(!item||typeof item.name!=='string'||!labels[item.state])continue;
          const li=document.createElement('li'),name=document.createElement('strong'),state=document.createElement('span');
          name.textContent=item.name;state.className='deployment-state';state.textContent=labels[item.state];li.append(name,state);
          if(typeof item.detail==='string'){const detail=document.createElement('small');detail.textContent=item.detail;li.append(detail)}
          const url=evidenceURL(item.evidence_url);
          if(url){const link=document.createElement('a');link.href=url;link.textContent='查看实际回执 ↗';li.append(link)}
          nodes.push(li);
        }
        if(nodes.length)list.replaceChildren(...nodes);
      }
      if(typeof audit.checked_at==='string'&&audit.checked_at){
        const note=document.querySelector('[data-deployment-updated]');
        if(note){const link=document.createElement('a');link.href='report-assets/deployment-status.json';link.textContent='查看当前状态数据';note.replaceChildren(document.createTextNode('核验更新时间：'+audit.checked_at+'。'),link)}
      }
    }
    const pdf=data.pdf,url=pdf&&localURL(pdf.href);
    if(pdf&&pdf.state==='ready'&&url&&typeof pdf.sha256==='string'&&/^[a-f0-9]{64}$/.test(pdf.sha256)){
      const check=await fetch(url,{method:'HEAD',cache:'no-store'});
      if(check.ok)for(const element of document.querySelectorAll('[data-pdf-control]')){
        const link=document.createElement('a');link.className='pdf-control';link.href=url;link.textContent='下载完整报告 PDF ↓';link.dataset.pdfControl='';link.dataset.pdfSha256=pdf.sha256;element.replaceWith(link);
      }
    }
  }catch{
    // The static pending notice remains readable offline or before publication.
  }
})();
