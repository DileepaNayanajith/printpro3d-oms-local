
const picks=[...document.querySelectorAll('[name="orders"]')],all=document.getElementById('all'),button=document.getElementById('print');
function update(){const n=picks.filter(p=>p.checked).length;document.getElementById('selected').textContent=n;document.getElementById('sheets').textContent=Math.ceil(n/2);button.disabled=n===0||n>200;all.checked=n>0&&n===picks.length;all.indeterminate=n>0&&n<picks.length;}
all.addEventListener('change',()=>{picks.forEach(p=>p.checked=all.checked);update();});picks.forEach(p=>p.addEventListener('change',update));document.getElementById('batch').addEventListener('submit',()=>{button.disabled=true;button.textContent='Queueing batch…';});
