const refresh=document.getElementById('dashboard-refreshing');
if(refresh) setTimeout(()=>{if(!document.hidden && !document.querySelector('details[open]') && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName))location.reload();},refresh.dataset.busy==='1'?8000:60000);
