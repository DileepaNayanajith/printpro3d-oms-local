(() => {
const mode=document.getElementById('product-mode');if(!mode)return;
const form=mode.form, qty=form.elements.quantity, cod=form.elements.cod, product=form.elements.product, colour=form.elements.rack_colour;
function update(){const rack=mode.value==='hot_wheels';document.getElementById('rack-colour-label').hidden=!rack;document.getElementById('rack-price-info').hidden=!rack;cod.readOnly=rack;product.readOnly=rack;
if(rack){const n=Number(qty.value);product.value='Hot Wheels rack '+colour.value;cod.value=Number.isInteger(n)&&n>0?((n>=3?1750:1800)*n+400).toFixed(2):'';}}
mode.addEventListener('change',update);qty.addEventListener('input',update);colour.addEventListener('change',update);update();
})();
