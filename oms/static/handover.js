(() => {
  const form=document.getElementById('handover-form'), input=document.getElementById('barcode'), result=document.getElementById('scan-result');
  const start=document.getElementById('camera-start'), stop=document.getElementById('camera-stop'), video=document.getElementById('scan-video'), next=document.getElementById('next-parcel'), submit=document.getElementById('record-button');
  let reader=null,busy=false;
  function stopCamera(){if(reader){reader.reset();reader=null}video.srcObject?.getTracks().forEach(t=>t.stop());video.srcObject=null;video.hidden=true;stop.hidden=true;start.disabled=false}
  function show(message,error=false){result.hidden=false;result.classList.toggle('error',error);result.textContent=message}
  async function record(value){
    if(busy)return;
    const code=value.trim().toUpperCase();if(!/^PP3D-\d{1,9}$/.test(code)){show('Scan the PP3D order barcode, not the courier sticker.',true);return}
    input.value=code;busy=true;submit.disabled=true;stopCamera();start.disabled=true;show('Saving parcel handover…');
    try{
      const response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});
      if(response.redirected){show('Session expired. Sign in again before scanning.',true);return}
      const data=await response.json();if(!response.ok)throw new Error(data.error || 'Could not save. Reload and retry the same order.');
      show(`${data.duplicate?'Already recorded — count unchanged':'OUT OF STORE · Recorded'}\n${data.reference}\n${data.name}\nCOD Rs. ${(data.cod_cents/100).toLocaleString('en-LK',{minimumFractionDigits:2})}`);
      result.style.whiteSpace='pre-line';document.getElementById('today-count').textContent=data.today_count;document.getElementById('total-count').textContent=data.total_count;next.hidden=false;
      if(!data.duplicate)navigator.vibrate?.(100);
    }catch(error){show(error instanceof SyntaxError?'Connection uncertain. Retry the same barcode; it will not be counted twice.':error.message,true)}
    finally{busy=false;submit.disabled=false;start.disabled=false}
  }
  async function openCamera(){
    stopCamera();
    if(!navigator.mediaDevices?.getUserMedia || !window.ZXing){show('Camera unavailable. Use your phone browser or enter the PP3D order ID below.',true);return}
    start.disabled=true;stop.hidden=false;video.hidden=false;next.hidden=true;
    const hints=new Map([[ZXing.DecodeHintType.POSSIBLE_FORMATS,[ZXing.BarcodeFormat.CODE_128]]]);
    reader=new ZXing.BrowserMultiFormatReader(hints);const active=reader;
    try{await active.decodeFromConstraints({video:{facingMode:{ideal:'environment'}},audio:false},video,(decoded)=>{if(decoded && !busy && reader===active)record(decoded.getText())});if(reader!==active)active.reset()}
    catch{stopCamera();show('Allow camera access in your browser, or enter the order ID below.',true)}
  }
  form.addEventListener('submit',e=>{e.preventDefault();record(input.value)});start.addEventListener('click',openCamera);stop.addEventListener('click',stopCamera);
  next.addEventListener('click',()=>{input.value='';result.hidden=true;openCamera()});window.addEventListener('pagehide',stopCamera);document.addEventListener('visibilitychange',()=>{if(document.hidden)stopCamera()});
})();
