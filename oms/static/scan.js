
const ref=document.getElementById('reference'),courier=document.getElementById('courier'),form=document.getElementById('scan'),send=document.getElementById('send'),feedback=document.getElementById('feedback');let busy=false;
ref.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();ref.value=ref.value.trim().toUpperCase();if(ref.reportValidity())courier.focus();}});
document.querySelectorAll('[data-ref]').forEach(b=>b.addEventListener('click',()=>{if(busy)return;ref.value=b.dataset.ref;courier.value='';courier.focus();}));
form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;send.disabled=true;const data=new FormData(form);ref.readOnly=courier.readOnly=true;
try{const r=await fetch('/scan',{method:'POST',body:data,headers:{Accept:'application/json'}});if(r.redirected){throw new Error('Session expired. Sign in again before scanning.');}if(!r.ok){const doc=new DOMParser().parseFromString(await r.text(),'text/html');throw new Error(doc.querySelector('main section p')?.textContent||'Scan was not accepted. Check order and sticker.');}const result=await r.json();feedback.className='success';feedback.textContent=`${data.get('reference')} · ${result.name}: queued for FDE. Scan the next order.`;ref.value='';courier.value='';document.querySelectorAll('[data-ref]').forEach(b=>{if(b.dataset.ref===data.get('reference'))b.closest('p').remove();});await progress();}
catch(error){feedback.className='error';feedback.textContent=error.message+' Values kept so you can check them. If the connection failed, check booking progress before retrying.';}
finally{busy=false;send.disabled=false;ref.readOnly=courier.readOnly=false;ref.focus();}});
const labels={queued:'Waiting for FDE',preparing:'Filling FDE',prepared:'Ready to submit',approved:'Submitting next',submitting:'Submitting once',succeeded:'Booked ✓',login_required:'FDE login needed',needs_review:'Check FDE result',blocked:'Needs attention'};
async function progress(){try{const r=await fetch('/scan/status',{headers:{Accept:'application/json'}});if(!r.ok||r.redirected)throw Error();const rows=await r.json(),box=document.getElementById('progress');box.replaceChildren();if(!rows.length){box.textContent='Your scanned orders will appear here.';return;}for(const row of rows.slice(0,8)){const item=document.createElement('div');item.className='status-row';const title=document.createElement('strong');title.textContent=`PP3D-${String(row.order_id).padStart(6,'0')} · ${labels[row.state]||row.state}`;const detail=document.createElement('small');detail.textContent=`${row.assigned_waybill} · ${row.message}`;item.append(title,detail);
if(box.dataset.manualBooking==='yes' && ['blocked','needs_review'].includes(row.state)){
 const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Booked manually in FDE';
 button.addEventListener('click',async()=>{
  if(!confirm(`Confirm you already booked PP3D-${String(row.order_id).padStart(6,'0')} in FDE with tracking ${row.assigned_waybill}? This only updates OMS; it does not submit another parcel.`))return;
  button.disabled=true;
  const data=new FormData();data.set('csrf',form.querySelector('[name="csrf"]').value);data.set('record_checked','yes');data.set('tracking',row.assigned_waybill);
  try{const result=await fetch(`/orders/${row.order_id}/booking`,{method:'POST',body:data,headers:{Accept:'application/json'}});
   if(!result.ok||result.redirected)throw Error('Could not confirm. Check the order status or sign in again.');
   await result.json();feedback.className='success';feedback.textContent=`PP3D-${String(row.order_id).padStart(6,'0')}: manual FDE booking recorded.`;await progress();
  }catch(error){feedback.className='error';feedback.textContent=error.message;button.disabled=false;}
 });item.append(button);
}
box.append(item);}}catch{document.getElementById('progress').textContent='Status unavailable. Refresh or sign in again.';}}
progress();setInterval(progress,5000);
