'use strict';

let data = null, tab = 'customer', customer = 1, driver = 1;

const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, ch => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;',
  '"': '&quot;', "'": '&#39;'
}[ch]));

const time = n =>
  `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`;

const slot = n => `${time(n)} – ${time(n + 12)}`;
const label = s => ({
  pending: 'بانتظار الموعد',
  scheduled: 'مجدولة',
  delivered: 'تم التسليم'
})[s] || s;

function showNotice(msg, error = false) {
  const el = $('notice');
  el.hidden = false;
  el.textContent = msg;
  el.className = 'notice' + (error ? ' error' : '');
  setTimeout(() => { el.hidden = true; }, 4900);
}

async function load() {
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw Error('تعذر جلب البيانات');
    data = await response.json();
    render();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function callAction(action, payload) {
  try {
    const response = await fetch('/api/' + action, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'لم تكتمل العملية');

    await load();
    showNotice('تم تنفيذ العملية بنجاح.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

function applyTheme(mode) {
  document.body.classList.toggle('dark', mode === 'dark');
  $('themeToggle').textContent =
    mode === 'dark' ? 'الوضع الفاتح' : 'الوضع الداكن';
  localStorage.setItem('smartDeliveryTheme', mode);
}

function toggleTheme() {
  applyTheme(
    document.body.classList.contains('dark') ? 'light' : 'dark'
  );
}

function saveNote() {
  callAction('note', {
    id: customer,
    note: $('customerNote').value
  });
}

function switchTab(value) {
  tab = value;
  render();
}

function selectCustomer(id) {
  customer = Number(id);
  render();
}

function selectDriver(id) {
  driver = Number(id);
  render();
}

function render() {
  if (!data) return;
  $('customerPage').hidden = tab !== 'customer';
  $('driverPage').hidden = tab !== 'driver';
  $('tabCustomer').classList.toggle('active', tab === 'customer');
  $('tabDriver').classList.toggle('active', tab === 'driver');

  if (tab === 'customer') renderCustomer();
  else renderDriver();
}

function renderCustomer() {
  const people = data.shipments;

  if (!people.some(s => s.id === customer)) {
    customer = people[0]?.id;
  }

  $('customerList').innerHTML = people.map(s => `
    <button
      class="customer-item ${s.id === customer ? 'selected' : ''}"
      onclick="selectCustomer(${s.id})"
    >
      <span class="itemtop">
        <strong>${esc(s.client)}</strong>
        <span class="chip ${esc(s.status)}">
          ${esc(label(s.status))}
        </span>
      </span>
      <span class="minor">
        ◈ ${esc(s.area)} · رقم الشحنة: SHP-${1000 + s.id}
      </span>
    </button>
  `).join('');

  const s = people.find(item => item.id === customer);
  if (!s) return;

  $('chatTitle').textContent =
    'مساعد التوصيل الذكي · ' + s.client;

  const steps = [
    'وصول المنطقة', 'تحديد الموعد',
    'جاري التوصيل', 'تم التسليم'
  ];

  const messages = data.messages[String(s.id)] || [];
  const hasArrival = messages.some(
    msg => msg.body === 'وصل مندوب التوصيل إلى موقع التسليم.'
  );

  let level = s.status === 'delivered' ? 4 :
              s.status === 'scheduled' ? 2 : 1;

  if (hasArrival && s.status === 'scheduled') level = 3;

  $('progress').innerHTML = steps.map((step, i) => `
    <div class="progress-step ${i < level ? 'done' : ''}">
      <span>${['▣', '◷', '➜', '✓'][i]}</span>
      ${step}
    </div>
  `).join('');

  $('chatMessages').innerHTML = messages.map(m => `
    <div class="bubble ${
      m.sender === 'العميل' ? 'customer' :
      m.sender === 'المندوب' ? 'driver' : 'system'
    }">
      <b>${esc(m.sender)}</b>
      <div>${esc(m.body)}</div>
      <time dir="ltr">${esc(m.created_at.slice(11))}</time>
    </div>
  `).join('');

  const noteField = $('customerNote');
  noteField.value = s.customer_note || '';
  noteField.disabled = s.status === 'delivered';

  $('noteCount').textContent = noteField.value.length + ' / 300';
  noteField.oninput = () => {
    $('noteCount').textContent = noteField.value.length + ' / 300';
  };

  const target = $('chatActions');

  if (s.status === 'pending' && data.today < s.delivery_date) {
    const options = (data.slots[String(s.id)] || []).map(item => `
      <option value="${item.minute}" ${item.free ? '' : 'disabled'}>
        ${item.free ? 'متاح' : 'محجوز'} · ${slot(item.minute)}
      </option>
    `).join('');

    target.innerHTML = `
      <div class="action-row">
        <select id="slotSelect" aria-label="اختر الموعد">
          ${options}
        </select>
        <button class="primary" onclick="confirmBooking(${s.id})">
          تأكيد الحجز
        </button>
      </div>
    `;

  } else if (s.status === 'scheduled') {
    const options = data.reschedule_slots[String(s.id)] || [];

    target.innerHTML = `
      <div class="action-row">
        <b>الموعد المؤكد:
          <span dir="ltr">${slot(s.slot)}</span>
        </b>

        ${
          options.length && !s.rescheduled_count
          ? `
            <select id="newSlot" aria-label="الموعد الجديد">
              ${options.map(v => `
                <option value="${v.minute}">
                  ${slot(v.minute)}
                </option>
              `).join('')}
            </select>
            <button class="secondary"
              onclick="confirmReschedule(${s.id})">
              تغيير الموعد (مرة واحدة)
            </button>
          `
          : `
            <small class="reschedule-lock">
              ${
                s.rescheduled_count
                ? 'تم استخدام محاولة التعديل'
                : 'التعديل متاح قبل الموعد بـ 5 ساعات'
              }
            </small>
          `
        }
      </div>
    `;

  } else if (s.status === 'delivered') {
    target.innerHTML = s.rating
      ? `
        <div class="success-message">
          تم التسليم · تقييمك ${s.rating} من 5 نجوم. شكرًا لك.
        </div>
      `
      : `
        <div class="action-row">
          <b>تم التسليم، كيف تقيم الخدمة؟</b>
          ${[1, 2, 3, 4, 5].map(n => `
            <button class="secondary"
              onclick="callAction('rate', {
                id:${s.id}, rating:${n}
              })">${n} ★</button>
          `).join('')}
        </div>
      `;

  } else {
    target.textContent = 'انتهت فترة الحجز المسبق.';
  }

  const chat = $('chatMessages');
  chat.scrollTop = chat.scrollHeight;
}

function confirmReschedule(id) {
  const el = $('newSlot');

  if (!el || !el.value) {
    showNotice('لا يوجد موعد جديد متاح.', true);
    return;
  }

  if (confirm(
    'سيتم تغيير موعدك مرة واحدة فقط ولن تتمكن من تعديله بعد التأكيد. هل توافق؟'
  )) {
    callAction('reschedule', {
      id,
      minute: Number(el.value)
    });
  }
}

function confirmBooking(id) {
  const el = $('slotSelect');

  if (!el || !el.value) {
    showNotice('اختر موعدًا من القائمة أولًا.', true);
    return;
  }

  callAction('book', {
    id,
    minute: Number(el.value)
  });
}

function positionKm(a, b) {
  const rad = x => x * Math.PI / 180;
  const lat = rad(b.lat - a.lat);
  const lon = rad(b.lon - a.lon);
  const p = rad(a.lat);
  const q = rad(b.lat);

  return 6371.0088 * 2 * Math.asin(
    Math.min(1, Math.sqrt(
      Math.sin(lat / 2) ** 2 +
      Math.cos(p) * Math.cos(q) * Math.sin(lon / 2) ** 2
    ))
  );
}

function renderDriver() {
  $('driverSelect').innerHTML = data.drivers.map(d => `
    <option value="${d.id}" ${driver === d.id ? 'selected' : ''}>
      المندوب: ${esc(d.name)}
    </option>
  `).join('');

  const owned = data.shipments.filter(
    s => s.driver_id === driver
  );

  const scheduled = owned.filter(
    s => s.status === 'scheduled'
  ).sort((a, b) => a.slot - b.slot);

  const delivered = owned.filter(
    s => s.status === 'delivered'
  ).length;

  $('stats').innerHTML = [
    ['إجمالي الشحنات', owned.length],
    ['مواعيد مؤكدة', scheduled.length],
    ['تم تسليمها', delivered]
  ].map(item => `
    <div class="panel stat">
      <span>${item[0]}</span>
      <strong>${item[1]}</strong>
    </div>
  `).join('');

  const base = {lat: 16.889, lon: 42.551};

  const byDistance = scheduled.map(s => ({
    ...s,
    distance: positionKm(base, s)
  })).sort((a, b) => a.distance - b.distance);

  const nearest = byDistance[0]?.id;
  const farthest = byDistance[byDistance.length - 1]?.id;

  $('shipmentRows').innerHTML = scheduled.length
    ? scheduled.map(s => `
      <tr>
        <td>
          <b>${esc(s.client)}</b>
          <small>
            ${esc(s.area)}
            ${s.id === nearest ? '· الأقرب' : ''}
            ${s.id === farthest && farthest !== nearest ? '· الأبعد' : ''}
          </small>
        </td>
        <td class="driver-note">
          ${esc(s.customer_note || '—')}
        </td>
        <td>${positionKm(base, s).toFixed(1)} كم</td>
        <td dir="ltr">${slot(s.slot)}</td>
        <td>
          <div class="row-actions">
            <button class="delay"
              onclick="callAction('delay_from', {
                driver_id:${driver},
                id:${s.id},
                minutes:15
              })">
              تأخير هذا العميل وما بعده +15 د
            </button>

            <button class="arrived"
              onclick="callAction('arrived', {
                driver_id:${driver},
                id:${s.id}
              })">
              وصلت إلى الموقع
            </button>

            <button
              onclick="callAction('deliver', {
                driver_id:${driver},
                id:${s.id}
              })">
              تسليم
            </button>
          </div>
        </td>
      </tr>
    `).join('')
    : `
      <tr>
        <td colspan="5"
          style="text-align:center;color:#8794a4;padding:35px">
          لا توجد حجوزات مؤكدة للمندوب.
          ابدأ بالحجز من بوابة العميل.
        </td>
      </tr>
    `;

  $('extremes').innerHTML = byDistance.length
    ? `
      <div>
        <strong>الأقرب</strong>
        ${esc(byDistance[0].client)}
        · ${byDistance[0].distance.toFixed(1)} كم
      </div>
      <div>
        <strong>الأبعد</strong>
        ${esc(byDistance[byDistance.length - 1].client)}
        · ${byDistance[byDistance.length - 1].distance.toFixed(1)} كم
      </div>
    `
    : '<div>اختر موعدًا لعرض المواقع.</div>';

  $('simDate').textContent = 'تاريخ المحاكاة: ' + data.today;
  drawMap(scheduled, base);
}

function drawMap(rows, origin) {
  const root = $('map');
  const W = 460, H = 350;

  const points = rows.map(s => ({
    lat: s.lat, lon: s.lon, id: s.id
  }));

  const all = [origin, ...points];
  const minLat = Math.min(...all.map(p => p.lat)) - .014;
  const maxLat = Math.max(...all.map(p => p.lat)) + .014;
  const minLon = Math.min(...all.map(p => p.lon)) - .014;
  const maxLon = Math.max(...all.map(p => p.lon)) + .014;

  const xy = p => [
    35 + (p.lon - minLon) / (maxLon - minLon) * (W - 70),
    35 + (maxLat - p.lat) / (maxLat - minLat) * (H - 70)
  ];

  const [x0, y0] = xy(origin);
  const seq = [origin, ...points];

  const path = seq.map(
    (p, i) => `${i ? 'L' : 'M'} ${xy(p).join(' ')}`
  ).join(' ');

  const grid = [75, 150, 225, 300, 375].map(x => `
    <path d="M ${x} 0 V 350"
      stroke="#d9e8e9" stroke-width="10"/>
  `).join('') + [65, 140, 215, 290].map(y => `
    <path d="M 0 ${y} H 460"
      stroke="#e0e9ea" stroke-width="9"/>
  `).join('');

  root.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}"
      xmlns="http://www.w3.org/2000/svg"
      role="img" aria-label="رسم توضيحي لمواقع الشحنات">
      <rect width="${W}" height="${H}" fill="#f0f7f6"/>
      ${grid}
      <path d="${path}" stroke="#059669"
        stroke-width="4" stroke-dasharray="8 5" fill="none"/>
      <circle cx="${x0}" cy="${y0}"
        r="13" fill="#2575cc" stroke="white" stroke-width="3"/>
      <text x="${x0}" y="${y0 - 19}"
        text-anchor="middle" font-family="Arial"
        font-size="13" fill="#145480">START</text>

      ${points.map((p, i) => {
        const [x, y] = xy(p);
        return `
          <circle cx="${x}" cy="${y}"
            r="14" fill="#059669" stroke="white" stroke-width="3"/>
          <text x="${x}" y="${y + 5}"
            text-anchor="middle" font-family="Arial"
            font-size="14" font-weight="bold" fill="white">
            ${i + 1}
          </text>
        `;
      }).join('')}
    </svg>
  `;
}

async function resetDemo() {
  if (confirm(
    'سيتم مسح جميع حجوزات ورسائل المحاكاة وإعادتها من البداية. هل تريد المتابعة؟'
  )) {
    await callAction('reset', {});
  }
}

applyTheme(
  localStorage.getItem('smartDeliveryTheme') === 'dark'
    ? 'dark' : 'light'
);

load();
