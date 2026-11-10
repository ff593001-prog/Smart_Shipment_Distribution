'use strict';
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pad = n => String(n).padStart(2,'0');
const fmtTime = n => `${pad(Math.floor(n/60))}:${pad(n%60)}`;
const slotLabel = (n,length=12) => `${fmtTime(n)} – ${fmtTime(n+length)}`;
const formatDay = d => {try{return new Intl.DateTimeFormat('ar-SA-u-ca-gregory',{dateStyle:'full'}).format(new Date(d+'T12:00:00'))}catch{return d}};
const statusText = s => ({pending:'بانتظار الجدولة',scheduled:'موعد مؤكد',delivered:'تم التسليم'})[s]||s;
let currentPage='welcome',selectedCustomer=1, customerData=null,driverData=null,loggedIn=false, activeDialog=null, toastTimer=null,skipChangeNotice=false;
let clientList=[],supportLoggedIn=false;
function notify(text,error=false){const t=$('toast');clearTimeout(toastTimer);t.textContent=text;t.className='toast'+(error?' error':'');t.hidden=false;toastTimer=setTimeout(()=>t.hidden=true,4800)}
async function api(url,method='GET',data){const opts={method,credentials:'same-origin',cache:'no-store'};if(data!==undefined){opts.headers={'Content-Type':'application/json'};opts.body=JSON.stringify(data)}const res=await fetch(url,opts);let j={};try{j=await res.json()}catch{};if(!res.ok)throw Error(j.error || 'تعذر الاتصال بالخادم');return j}
function setTheme(on){document.body.classList.toggle('dark',!!on);$('themeInput').checked=!!on;localStorage.setItem('sd_theme',on?'dark':'light')}
function toggleMenu(force){const open=typeof force==='boolean'?force:!$('sidebar').classList.contains('open');$('sidebar').classList.toggle('open',open);$('backdrop').hidden=!open;$('menuBtn').setAttribute('aria-expanded',String(open))}
function navigate(page){currentPage=page;for(const name of ['welcome','customer','driver','support','supportDesk','future']) $(name+'Page').hidden=name!==page;toggleMenu(false);window.scrollTo({top:0,behavior:'smooth'});if(page==='driver')refreshDriver();if(page==='support')renderSupport();if(page==='supportDesk')refreshSupportDesk();if(page==='customer')refreshCustomer()}
function setCustomer(id){selectedCustomer=Number(id)||1;localStorage.setItem('sd_demo_customer',String(selectedCustomer));customerData=null;skipChangeNotice=true;refreshCustomer()}
function dataBusy(){const a=document.activeElement;return a && ['INPUT','TEXTAREA','SELECT'].includes(a.tagName)}
async function loadDemoClients(){const res=await api('/api/demo/clients');clientList=res.customers||[];if(!clientList.some(x=>x.id===selectedCustomer))selectedCustomer=clientList[0]?.id||1;const s=$('customerSelect');s.innerHTML=clientList.map(x=>`<option value="${x.id}">${esc(x.client)} · SHP-${1000+x.id}</option>`).join('');s.value=String(selectedCustomer)}
async function refreshCustomer(){try{const item=await api(`/api/customer/${selectedCustomer}`);const prev=customerData?.shipment;customerData=item;
  const changed=prev && prev.slot!==item.shipment.slot && !skipChangeNotice;
  if(currentPage==='customer'&&!dataBusy()) renderCustomer();
  if(currentPage==='support'&&!dataBusy())renderSupport();

  if(changed)notify('تم تحديث موعد الشحنة تلقائيا. راجع آخر التحديثات.');
  skipChangeNotice=false;
}catch(e){if(currentPage!=='welcome')notify(e.message,true)}}
function customerFacts(sh){return [
  ['رقم الشحنة',`SHP-${1000+sh.id}`],['اسم المستلم',sh.client],['مدينة التسليم','خميس مشيط'],['الحي السكني',sh.area]
 ].map(([k,v])=>`<div><small>${esc(k)}</small><b>${esc(v)}</b></div>`).join('')}
function renderTimeline(sh){const steps=[['تجهيز الشحنة','مركز الإرسال · الرياض'],['مغادرة مركز الرياض','نقل محلي'],['الوصول إلى منطقة عسير','مركز الفرز'],['الوصول لمستودع المدينة','خميس مشيط'],['التسليم للعنوان','بعد الحجز']];const level=sh.status==='delivered'?5:4;
 $('timeline').innerHTML=steps.map(([title,sub],i)=>`<div class="timeline-item ${i<level?'done':''}"><span class="dot">${i<level?'✓':'○'}</span><div><strong>${title}</strong><small>${sub}</small></div></div>`).join('')}
function renderMessages(msgs){$('customerMessages').innerHTML=msgs.length?msgs.slice(-12).map(m=>`<div class="message ${m.sender==='المندوب'?'driver':m.sender==='العميل'?'customer':''}"><b>${esc(m.sender)}</b><p>${esc(m.body)}</p><small dir="ltr">${esc(m.created_at)}</small></div>`).join(''):'<p class="date-hint">لا توجد تحديثات بعد.</p>'}
function renderCustomer(){if(!customerData)return;const {shipment:s,slots,reschedule_slots,messages,slot_minutes}=customerData;
 $('customerSelect').value=String(selectedCustomer);
 $('shipmentTitle').textContent=`شحنة ${s.client}`;
 $('customerStatus').className='chip '+esc(s.status);$('customerStatus').textContent=statusText(s.status);
 $('shipmentFacts').innerHTML=customerFacts(s);
 renderTimeline(s);renderMessages(messages||[]);
 $('customerNote').value=s.customer_note||'';$('customerNote').disabled=s.status==='delivered';
 $('welcomeMessage').textContent=`مرحبا ${s.client.split(' ')[0]}، وصلت شحنتك إلى مستودع شركة الشحن في خميس مشيط. يرجى اختيار الوقت المناسب لتسليمها إلى عنوانك المسجل في ${s.area} ${formatDay(s.delivery_date)}.`;
 const area=$('bookingArea');let html='';
 if(s.status==='pending'&&customerData.today<s.delivery_date){const options=(slots||[]).filter(v=>v.free);html=options.length?`<div class="book-inner"><label>المواعيد المتاحة <select id="bookingSlot">${options.map(v=>`<option value="${v.minute}">${slotLabel(v.minute,slot_minutes)}</option>`).join('')}</select></label><button class="btn btn-primary" onclick="startBooking()">تأكيد الموعد</button></div><small class="date-hint">يتم اختيار الموعد مسبقا، والمواعيد المحجوزة غير متاحة.</small>`:'<div class="booked-box">لا توجد أوقات متاحة حاليا لهذه الشحنة.</div>'}
 else if(s.status==='scheduled'){let extra='';if((reschedule_slots||[]).length){extra=`<div class="resched-controls"><label>اختيار موعد بديل <select id="rescheduleSlot">${reschedule_slots.map(v=>`<option value="${v.minute}">${slotLabel(v.minute,slot_minutes)}</option>`).join('')}</select></label><button class="btn btn-outline" onclick="startReschedule()">تعديل الموعد</button></div><small class="date-hint">يسمح بتعديل واحد فقط قبل الموعد بخمس ساعات على الأقل.</small>`}else{extra=`<div class="lock-note">${s.rescheduled_count?'تم استخدام فرصة تعديل الموعد.':'لا يمكن تعديل الموعد إلا قبل التسليم بخمس ساعات على الأقل.'}</div>`}
 html=`<div class="booked-box"><strong>✓ تم تأكيد موعد التوصيل</strong><p>${formatDay(s.delivery_date)} · <span dir="ltr">${slotLabel(s.slot,slot_minutes)}</span></p>${extra}</div>`}
 else if(s.status==='delivered'){html=`<div class="booked-box"><strong>✓ تم تسليم الشحنة</strong><p>اكتملت رحلة الشحنة. شكرا لاستخدام التجربة.</p>${s.rating?`<small>تقييمك: ${s.rating} من 5</small>`:`<div class="rate-row">${[1,2,3,4,5].map(n=>`<button onclick="rateShipment(${n})">${n} ★</button>`).join('')}</div>`}</div>`}
 else html='<div class="booked-box">انتهى وقت حجز موعد هذه الشحنة في المحاكاة.</div>';
 area.innerHTML=html}
function openDialog(title,text,onConfirm,yes='تأكيد الحجز',no='العودة لتغيير الموعد'){$('confirmTitle').textContent=title;$('confirmText').textContent=text;$('acceptConfirm').textContent=yes;$('cancelConfirm').textContent=no;activeDialog=onConfirm;$('confirmDialog').hidden=false;$('acceptConfirm').onclick=()=>{const action=activeDialog;closeDialog();action?.()}}
function closeDialog(){$('confirmDialog').hidden=true;activeDialog=null}
function startBooking(){const v=Number($('bookingSlot')?.value);if(!Number.isInteger(v)){notify('اختر الموعد أولا.',true);return}openDialog('تنبيه مهم قبل الحجز',`موعد التسليم المحدد ${slotLabel(v)}. يسمح بتعديل الموعد مرة واحدة فقط، قبل موعد التسليم بخمس ساعات على الأقل. هل تريد تأكيد الحجز؟`,()=>customerAct('book',{minute:v}))}
function startReschedule(){const v=Number($('rescheduleSlot')?.value);if(!Number.isInteger(v)){notify('اختر الموعد البديل.',true);return}openDialog('تأكيد تعديل الموعد',`سيتم اعتماد الموعد الجديد ${slotLabel(v)}، ولن يكون بإمكانك تعديله مرة أخرى. هل أنت متأكد؟`,()=>customerAct('reschedule',{minute:v}),'تأكيد التعديل')}
async function customerAct(action,d){try{skipChangeNotice=true;await api(`/api/customer/${selectedCustomer}/${action}`,'POST',d);await refreshCustomer();notify('تم حفظ التغيير بنجاح.')}catch(e){skipChangeNotice=false;notify(e.message,true)}}
function saveNote(){customerAct('note',{note:$('customerNote').value})}
function rateShipment(n){customerAct('rate',{rating:n})}

async function refreshDriver(){try{const ss=await api('/api/driver/session');loggedIn=!!ss.logged_in;$('driverLogin').hidden=loggedIn;$('driverDashboard').hidden=!loggedIn;if(!loggedIn)return;driverData=await api('/api/driver/state');if(currentPage==='driver')renderDriver()}catch(e){loggedIn=false;$('driverLogin').hidden=false;$('driverDashboard').hidden=true;notify(e.message,true)}}
async function loginDriver(event){event.preventDefault();try{await api('/api/driver/login','POST',{username:$('driverUser').value.trim(),password:$('driverPass').value});await refreshDriver();notify('تم تسجيل الدخول إلى البوابة التجريبية.')}catch(e){notify(e.message,true)}}
async function logoutDriver(){await api('/api/driver/logout','POST',{});loggedIn=false;driverData=null;await refreshDriver();notify('تم تسجيل الخروج.');}
const dStatus=(s)=>statusText(s && typeof s==='object' ? s.status : s);
const ticketNo=id=>`TKT-${String(id).padStart(4,'0')}`;
function renderDriver(){if(!driverData)return;const a=driverData.shipments||[];const scheduled=a.filter(s=>s.status==='scheduled'),delivered=a.filter(s=>s.status==='delivered');const total=a.length;
 $('driverHello').textContent=`مرحبا ${driverData.driver.name} · تاريخ المحاكاة: ${formatDay(driverData.today)}`;
 $('driverStats').innerHTML=[['الشحنات في السجل',total],['مواعيد مؤكدة',scheduled.length],['تم التسليم',delivered.length]].map(([k,v])=>`<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');
 const ordered=[...scheduled].sort((a,b)=>a.delivery_date.localeCompare(b.delivery_date)||a.slot-b.slot).concat(delivered);
 $('driverShipments').innerHTML=ordered.map((s,i)=>{
  const canAct=s.status==='scheduled'&&s.delivery_date===driverData.today;
  let action='';if(canAct) action=`${s.delivery_date===driverData.today?`<button class="btn btn-quiet" onclick="driverAct('arrived',${s.id})">وصلت للموقع</button>`:''}<select class="delay-select" id="delay${s.id}"><option value="15">تأخير 15 دقيقة</option><option value="30">30 دقيقة</option><option value="45">45 دقيقة</option><option value="60">60 دقيقة</option></select><button class="btn btn-outline" onclick="delayAfter(${s.id})">تأخير ما بعد هذه الشحنة</button>${s.delivery_date===driverData.today?`<button class="btn btn-primary" onclick="driverAct('deliver',${s.id})">تم التسليم</button>`:''}`;
  return `<div class="shipment-row"><div class="shipment-meta"><strong>${esc(s.client)} <span class="chip ${s.status}">${dStatus(s)}</span></strong><small>SHP-${1000+s.id} · ${esc(s.area)} · ${formatDay(s.delivery_date)}</small>${s.customer_note?`<small>ملاحظة العميل: ${esc(s.customer_note)}</small>`:''}</div><div class="time-pill">${s.slot!==null?slotLabel(s.slot,driverData.slot_minutes):'لم يحدد الموعد'}</div>${action?`<div class="shipment-actions">${action}</div>`:''}</div>`
 }).join('') || '<p>لا توجد مواعيد مؤكدة بعد. ستظهر الشحنات هنا بعد اختيار العميل للموعد.</p>';
 drawDriverMap(scheduled)}
function km(a,b){const R=6371,rad=v=>v*Math.PI/180;let dl=rad(b.lat-a.lat),dn=rad(b.lon-a.lon);const h=Math.sin(dl/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.lat))*Math.sin(dn/2)**2;return 2*R*Math.asin(Math.min(1,Math.sqrt(h)))}
function drawDriverMap(rows){const map=$('driverMap'),leg=$('distanceLegend');if(!rows.length){map.innerHTML='<div style="padding:60px 15px;text-align:center">تظهر المواقع بمجرد جدولة الشحنات.</div>';leg.innerHTML='';return}
 const ordered=[...rows].sort((a,b)=>a.slot-b.slot);const points=ordered.map((s,i)=>({...s,num:i+1}));const origin={lat:18.303,lon:42.733};const all=[origin,...points];const latmin=Math.min(...all.map(x=>x.lat))-.012,latmax=Math.max(...all.map(x=>x.lat))+.012,lonmin=Math.min(...all.map(x=>x.lon))-.014,lonmax=Math.max(...all.map(x=>x.lon))+.014;
 const xy=p=>[30+(p.lon-lonmin)/(lonmax-lonmin)*430,30+(latmax-p.lat)/(latmax-latmin)*270];const pa=[origin,...points].map((v,i)=>`${i?'L':'M'} ${xy(v).join(' ')}`).join(' ');const grid=[70,145,220,295,370].map(x=>`<path d="M${x} 0V340"/>`).join('')+[65,130,195,260].map(y=>`<path d="M0 ${y}H500"/>`).join('');const [x,y]=xy(origin);
 map.innerHTML=`<svg viewBox="0 0 500 340" role="img" aria-label="خريطة توضيحية لشحنات المندوب"><rect width="500" height="340" fill="#edf6f6"/><g stroke="#d5e8eb" stroke-width="14">${grid}</g><path d="${pa}" fill="none" stroke="#078f80" stroke-width="4" stroke-dasharray="9 9"/><circle cx="${x}" cy="${y}" r="15" fill="#2f607a" stroke="white" stroke-width="4"/><text x="${x}" y="${y-23}" text-anchor="middle" font-size="13" fill="#25485c">المركز</text>${points.map(p=>{const [x,y]=xy(p);return `<g><circle cx="${x}" cy="${y}" r="17" fill="#0a9f87" stroke="white" stroke-width="4"/><text x="${x}" y="${y+5}" text-anchor="middle" font-size="14" fill="white" font-weight="bold">${p.num}</text></g>`}).join('')}</svg>`;
 const distances=points.map(p=>km(origin,p));const nearest=Math.min(...distances),farthest=Math.max(...distances);
 leg.innerHTML=points.map((p,i)=>`<div><span>${i+1}. ${esc(p.area)} · <span dir="ltr">${fmtTime(p.slot)}</span> ${distances.length>1&&distances[i]===nearest?'· الأقرب':''}${distances.length>1&&distances[i]===farthest?'· الأبعد':''}</span><b>${distances[i].toFixed(1)} كم</b></div>`).join('')}
async function driverAct(action,id){try{let ask=action==='deliver'?'هل تم تسليم الشحنة إلى العميل؟':'هل وصل المندوب إلى موقع العميل؟';openDialog('تأكيد الإجراء',ask,async()=>{try{await api(`/api/driver/${action}`,'POST',{id});await refreshDriver();await refreshCustomer();notify('تم تحديث الحالة لدى العميل والمندوب.')}catch(e){notify(e.message,true)}},'نعم، تأكيد','إلغاء')}catch(e){notify(e.message,true)}}
function delayAfter(id){const mins=Number($('delay'+id)?.value||15);openDialog('محاكاة تأخير المندوب',`سيضاف ${mins} دقيقة إلى مواعيد الشحنات اللاحقة فقط، من دون تغيير موعد الشحنة المحددة. هل تريد المتابعة؟`,async()=>{try{const res=await api('/api/driver/delay_from','POST',{id,minutes:mins});await refreshDriver();await refreshCustomer();notify(`تحديث ناجح: تأثرت ${res.affected} شحنة لاحقة، وتم إشعار عملائها داخل النظام.`)}catch(e){notify(e.message,true)}},'تطبيق التأخير','إلغاء')}
async function advanceDemo(){openDialog('الانتقال ليوم التوصيل','هذه خطوة محاكاة تغير تاريخ النظام المشترك ليصبح يوم التسليم، وتسمح للمندوب بتأكيد الوصول والتسليم.',async()=>{try{await api('/api/driver/advance','POST',{});await refreshDriver();await refreshCustomer();notify('تم الانتقال إلى يوم التسليم في المحاكاة.')}catch(e){notify(e.message,true)}},'انتقال','إلغاء')}
function resetDemo(){openDialog('إعادة فتح التجربة','ستلغى المواعيد والتأخيرات وتذاكر الدعم التجريبية، وتبقى الشحنات موزعة على المندوبين بانتظار حجز العميل. لا تستخدم هذا الخيار على بيانات حقيقية.',async()=>{try{await api('/api/driver/reset','POST',{});await refreshDriver();await refreshCustomer();notify('بدأت تجربة جديدة: جميع الشحنات بانتظار حجز العميل.')}catch(e){notify(e.message,true)}},'إعادة الضبط','إلغاء')}

let categories=['تأخر موعد التوصيل','شحنتي لم تصل','استفسار عن سبب التأخير','مشكلة في حجز أو تعديل الموعد','تعذر التواصل مع المندوب','أخرى'];
function renderSupport(){if(!customerData)return;const s=customerData.shipment;$('supportIdentity').innerHTML=`<b>${esc(s.client)} · SHP-${1000+s.id}</b><span>الحالة: ${statusText(s.status)} · ${s.slot!==null?`آخر موعد: ${slotLabel(s.slot)}`:'بانتظار جدولة الموعد'}</span>`;const list=customerData.tickets||[];
 $('ticketHistory').innerHTML=list.length?list.map(t=>`<div class="ticket"><div class="ticket-top"><strong>${ticketNo(t.id)}</strong><span class="chip">${esc(t.status)}</span></div><p><b>${esc(t.category)}</b></p>${t.description?`<p>${esc(t.description)}</p>`:''}<blockquote>${esc(t.reply)}</blockquote><small class="date-hint">${esc(t.created_at)}</small> </div>`).join(''):'<p class="date-hint">لم تنشأ تذاكر حتى الآن. يمكنك إرسال طلب جديد.</p>'}
async function submitTicket(e){e.preventDefault();try{const data=await api(`/api/customer/${selectedCustomer}/ticket`,'POST',{category:$('ticketCategory').value,description:$('ticketDescription').value});$('ticketDescription').value='';await refreshCustomer();notify(`تم إنشاء ${data.ticket_no} والرد الآلي ظاهر في سجل التذاكر.`)}catch(e){notify(e.message,true)}}


async function refreshSupportDesk(){
 try{
  const ss=await api('/api/support/session');
  supportLoggedIn=!!ss.logged_in;
  $('supportLogin').hidden=supportLoggedIn;
  $('supportDashboard').hidden=!supportLoggedIn;
  if(!supportLoggedIn)return;
  const data=await api('/api/support/tickets');
  if(currentPage==='supportDesk'&&!dataBusy())renderSupportDesk(data.tickets||[]);
 }catch(e){notify(e.message,true)}
}
async function loginSupport(event){
 event.preventDefault();
 try{
  await api('/api/support/login','POST',{username:$('supportUser').value.trim(),password:$('supportPass').value});
  await refreshSupportDesk();notify('تم تسجيل الدخول إلى الدعم الفني.');
 }catch(e){notify(e.message,true)}
}
async function logoutSupport(){
 try{await api('/api/support/logout','POST',{});supportLoggedIn=false;await refreshSupportDesk();notify('تم تسجيل الخروج.')}catch(e){notify(e.message,true)}
}
function renderSupportDesk(tickets){
 $('supportDeskTickets').innerHTML=tickets.length?tickets.map(t=>`
   <section class="panel staff-ticket">
    <div class="ticket-top"><strong>${ticketNo(t.id)} · ${esc(t.client)}</strong><span class="chip">${esc(t.status)}</span></div>
    <p>${esc(t.category)} · SHP-${1000+t.shipment_id} · ${esc(t.area)}</p>
    <p>${esc(t.description||'لم يقدم العميل وصفا إضافيا.')}</p>
    <label>رد الموظف<textarea id="staffReply${t.id}" rows="2" maxlength="600">${esc(t.reply)}</textarea></label>
    <div class="staff-ticket-controls"><label>الحالة<select id="staffStatus${t.id}"><option ${t.status==='جديدة'?'selected':''}>جديدة</option><option ${t.status==='قيد المعالجة'?'selected':''}>قيد المعالجة</option><option ${t.status==='تم الحل'?'selected':''}>تم الحل</option></select></label><button class="btn btn-primary" onclick="saveStaffReply(${t.id})">حفظ الرد وإبلاغ العميل</button></div>
   </section>`).join(''):'<section class="panel empty-state">لا توجد تذاكر دعم حتى الآن.</section>';
}
async function saveStaffReply(id){
 try{
  await api(`/api/support/tickets/${id}/reply`,'POST',{reply:$('staffReply'+id).value,status:$('staffStatus'+id).value});
  await refreshSupportDesk();await refreshCustomer();notify('تم حفظ الرد وتحديث حالة التذكرة عند العميل.');
 }catch(e){notify(e.message,true)}
}

async function init(){setTheme(localStorage.getItem('sd_theme')==='dark');selectedCustomer=Number(localStorage.getItem('sd_demo_customer')||1);const dropdown=$('ticketCategory');dropdown.innerHTML='<option value="">اختر نوع المشكلة</option>'+categories.map(x=>`<option>${x}</option>`).join('');
 try{const meta=await api('/api/meta');categories=meta.ticket_categories||categories;dropdown.innerHTML='<option value="">اختر نوع المشكلة</option>'+categories.map(x=>`<option>${esc(x)}</option>`).join('');await loadDemoClients();await refreshCustomer();}catch(e){notify(e.message,true)}
 setInterval(async()=>{if(document.hidden)return;await refreshCustomer();if(currentPage==='driver' && loggedIn && !dataBusy())await refreshDriver();if(currentPage==='supportDesk' && supportLoggedIn && !dataBusy())await refreshSupportDesk()},3000);
}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('confirmDialog').hidden?toggleMenu(false):closeDialog()}});
init();
