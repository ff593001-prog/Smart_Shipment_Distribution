"""SQLite storage and scheduling for a local educational simulation."""
import hashlib
import math
import sqlite3
from datetime import timezone
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def saudi_today():
    return datetime.now(ZoneInfo('Asia/Riyadh')).date().isoformat()
from pathlib import Path

DB_PATH = Path(__file__).with_name('smart_delivery.sqlite3')
SLOT = 12
AREAS = {
    'حي الضيافة': (18.306, 42.742),
    'حي الرصراص': (18.280, 42.730),
    'حي العزيزية': (18.307, 42.720),
    'حي الهميلة': (18.320, 42.760),
    'حي الموسى': (18.289, 42.775),
    'حي النخيل': (18.294, 42.747),
}
DRIVERS = [
    ('أحمد', 'حي الضيافة', 'حي الرصراص'),
    ('خالد', 'حي العزيزية', 'حي الهميلة'),
    ('ياسر', 'حي الموسى', 'حي النخيل'),
]
CLIENTS = [
    ('عبدالله عسيري','حي الضيافة',1,'صباحي'),
    ('ماجد الشهراني','حي الضيافة',1,'صباحي'),
    ('ناصر القحطاني','حي الضيافة',1,'صباحي'),
    ('فارس الغامدي','حي الضيافة',1,'صباحي'),
    ('محمد العسيري','حي الرصراص',1,'مسائي'),
    ('سعد القحطاني','حي العزيزية',2,'صباحي'),
    ('فيصل المالكي','حي العزيزية',2,'صباحي'),
    ('خالد العتيبي','حي الهميلة',2,'مسائي'),
    ('سالم الدوسري','حي الموسى',3,'صباحي'),
    ('فهد الشهراني','حي الموسى',3,'صباحي'),
    ('يحيى حكمي','حي النخيل',3,'مسائي'),
]

class LogicError(Exception): pass

@contextmanager
def connect(path=DB_PATH):
    db=sqlite3.connect(str(path), timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db: yield db
    finally: db.close()

def setup(path=DB_PATH):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drivers (id INTEGER PRIMARY KEY,name TEXT NOT NULL,morning TEXT NOT NULL,evening TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS shipments (id INTEGER PRIMARY KEY, client TEXT NOT NULL, area TEXT NOT NULL, driver_id INTEGER NOT NULL REFERENCES drivers(id),period TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',slot INTEGER,rating INTEGER,delivery_date TEXT NOT NULL,lat REAL NOT NULL,lon REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT,shipment_id INTEGER NOT NULL REFERENCES shipments(id),sender TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS delays (driver_id INTEGER NOT NULL,delivery_date TEXT NOT NULL,minutes INTEGER NOT NULL,PRIMARY KEY(driver_id,delivery_date));
        CREATE UNIQUE INDEX IF NOT EXISTS unique_booking ON shipments(driver_id,delivery_date,slot) WHERE slot IS NOT NULL AND status!='cancelled';
        ''')
        # Upgrade existing databases in place without deleting shipments or bookings.
        existing_columns = {r['name'] for r in db.execute('PRAGMA table_info(shipments)')}
        if 'customer_note' not in existing_columns:
            db.execute("ALTER TABLE shipments ADD COLUMN customer_note TEXT NOT NULL DEFAULT ''")
        if 'rescheduled_count' not in existing_columns:
            db.execute('ALTER TABLE shipments ADD COLUMN rescheduled_count INTEGER NOT NULL DEFAULT 0')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES shipments(id),
            category TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reply TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'جديدة',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_shipment ON support_tickets(shipment_id);
        ''')
        if not db.execute('SELECT 1 FROM settings').fetchone(): db.execute('INSERT INTO settings VALUES (?,?)',('today',saudi_today()))
        if not db.execute('SELECT 1 FROM drivers').fetchone():
            for i,(name,m,e) in enumerate(DRIVERS,1): db.execute('INSERT INTO drivers VALUES (?,?,?,?)',(i,name,m,e))
        if not db.execute('SELECT 1 FROM shipments').fetchone(): _seed(db)

def _msg(db,sid,sender,body):
    db.execute('INSERT INTO messages(shipment_id,sender,body,created_at) VALUES(?,?,?,?)',(sid,sender,body,datetime.now().strftime('%Y-%m-%d %H:%M')))

def _seed(db):
    today=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
    date=(datetime.fromisoformat(today)+timedelta(days=1)).date().isoformat()
    for i,(name,area,driver,period) in enumerate(CLIENTS,1):
        lat,lon=AREAS[area]
        raw=hashlib.sha256(f'{i}|{area}'.encode()).digest()
        lat+=(int.from_bytes(raw[:2],'big')/65535-.5)*.012
        lon+=(int.from_bytes(raw[2:4],'big')/65535-.5)*.012
        db.execute('INSERT INTO shipments(id,client,area,driver_id,period,status,slot,rating,delivery_date,lat,lon) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(i,name,area,driver,period,'pending',None,None,date,lat,lon))
        _msg(db,i,'النظام',f'مرحبا {name.split()[0]}، وصلت شحنتك إلى مركز توزيع خميس مشيط. يرجى اختيار موعد مناسب لتسليمها غدا إلى عنوانك المسجل.')

def state(path=DB_PATH):
    with connect(path) as db:
        day=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        shipments=[dict(row) for row in db.execute('SELECT * FROM shipments ORDER BY id')]
        drivers=[dict(row) for row in db.execute('SELECT * FROM drivers ORDER BY id')]
        messages={str(s['id']):[dict(r) for r in db.execute('SELECT sender,body,created_at FROM messages WHERE shipment_id=? ORDER BY id',(s['id'],))] for s in shipments}
        delays=[dict(row) for row in db.execute('SELECT * FROM delays')]
        return {'today':day,'shipments':shipments,'drivers':drivers,'messages':messages,'delays':delays,'slots':{str(s['id']):available(db,s) for s in shipments if s['status']=='pending'}, 'reschedule_slots':{str(s['id']):reschedule_options(db,s) for s in shipments if s['status']=='scheduled'}}

def available(db,sh):
    start,end=(540,660) if sh['period']=='صباحي' else (780,960)
    row=db.execute('SELECT minutes FROM delays WHERE driver_id=? AND delivery_date=?',(sh['driver_id'],sh['delivery_date'])).fetchone()
    offset=row['minutes'] if row else 0
    occupied=[r['slot'] for r in db.execute("SELECT slot FROM shipments WHERE driver_id=? AND delivery_date=? AND slot IS NOT NULL AND status!='cancelled'",(sh['driver_id'],sh['delivery_date']))]
    return [{'minute':t+offset,'free':not any(t+offset < x+SLOT and t+offset+SLOT > x for x in occupied)} for t in range(start,end,SLOT) if t+offset+SLOT<=end]

def book(sid,minute,path=DB_PATH):
    if type(minute) is not int: raise LogicError('اختر موعدا صالحا.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh=db.execute('SELECT * FROM shipments WHERE id=?',(sid,)).fetchone()
        if sh is None: raise LogicError('الشحنة غير موجودة.')
        today=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        if today>=sh['delivery_date']: raise LogicError('انتهت فترة الحجز المسبق.')
        if sh['status']!='pending': raise LogicError('تم حجز هذه الشحنة بالفعل.')
        if minute not in {item['minute'] for item in available(db,sh) if item['free']}: raise LogicError('هذا الموعد غير متاح.')
        try: db.execute("UPDATE shipments SET status='scheduled',slot=? WHERE id=?",(minute,sid))
        except sqlite3.IntegrityError: raise LogicError('تم حجز الموعد من عميل آخر.')
        _msg(db,sid,'العميل',f'أرغب في استلام الشحنة من {label(minute)}.')
        _msg(db,sid,'النظام',f'تم تأكيد موعدك بنجاح: {label(minute)}. شكرا لتعاونك.')

def label(minute):
    def f(n): return f'{n//60:02d}:{n%60:02d}'
    return f'{f(minute)} – {f(minute+SLOT)}'

def _sim_now(db):
    'Current Saudi time when sim day is real today; otherwise midnight of sim day.'
    from datetime import timezone
    saudi = timezone(timedelta(hours=3))
    real_now = datetime.now(saudi)
    day = db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
    if day == real_now.date().isoformat():
        return real_now
    return datetime.fromisoformat(day).replace(tzinfo=saudi)


def _five_hours_left(db, sh):
    from datetime import timezone
    saudi = timezone(timedelta(hours=3))
    delivery = datetime.fromisoformat(sh['delivery_date']).replace(tzinfo=saudi)
    delivery += timedelta(minutes=sh['slot'])
    return delivery - _sim_now(db) >= timedelta(hours=5)


def reschedule_options(db, sh):
    'Return available substitute times; original slot stays reserved until confirmation.'
    if sh['status'] != 'scheduled' or sh['rescheduled_count'] >= 1 or not _five_hours_left(db, sh):
        return []
    choices = available(db, sh)
    # Current booking remains in DB; only another free slot is allowed.
    from datetime import timezone
    saudi = timezone(timedelta(hours=3))
    now = _sim_now(db)
    return [v for v in choices if v['free'] and v['minute'] != sh['slot']
            and datetime.fromisoformat(sh['delivery_date']).replace(tzinfo=saudi)
            + timedelta(minutes=v['minute']) - now >= timedelta(hours=5)]


def reschedule(sid, minute, path=DB_PATH):
    'One atomic change, once per shipment, at least five hours before both slots.'
    if type(minute) is not int:
        raise LogicError('اختر موعدا صحيحا.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh = db.execute('SELECT * FROM shipments WHERE id=?', (sid,)).fetchone()
        if not sh or sh['status'] != 'scheduled':
            raise LogicError('هذه الشحنة غير قابلة لتعديل الموعد.')
        if sh['rescheduled_count'] >= 1:
            raise LogicError('استخدمت محاولة تغيير الموعد الوحيدة لهذه الشحنة.')
        if not _five_hours_left(db, sh):
            raise LogicError('يسمح بالتغيير قبل الموعد بخمس ساعات على الأقل.')
        valid = {v['minute'] for v in reschedule_options(db, sh)}
        if minute not in valid:
            raise LogicError('الموعد الجديد غير متاح أو يقل عن خمس ساعات من الآن.')
        old_slot = sh['slot']
        try:
            db.execute('UPDATE shipments SET slot=?, rescheduled_count=1 WHERE id=?', (minute, sid))
        except sqlite3.IntegrityError as exc:
            raise LogicError('الموعد الجديد حجز للتو، اختر موعدا آخر.') from exc
        _msg(db, sid, 'العميل', f'طلبت تعديل الموعد من {label(old_slot)} إلى {label(minute)}.')
        _msg(db, sid, 'النظام', f'تم اعتماد الموعد الجديد: {label(minute)}. استخدمت محاولة التعديل الوحيدة.')


def delay_from(driver_id, sid, minutes=15, path=DB_PATH):
    """Shift only later bookings, atomically; allow one-hour contingency buffer."""
    if type(minutes) is not int or minutes not in (15,30,45,60):
        raise LogicError('اختر مدة تأخير صحيحة.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        day=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        target=db.execute('SELECT * FROM shipments WHERE id=? AND driver_id=?',(sid,driver_id)).fetchone()
        if not target or target['status']!='scheduled' or target['slot'] is None:
            raise LogicError('اختر شحنة مجدولة أولا.')
        if target['delivery_date'] != day:
            raise LogicError('لا يمكن تسجيل التأخير إلا بعد بدء يوم التوصيل التجريبي.')
        affected=list(db.execute("SELECT * FROM shipments WHERE driver_id=? AND delivery_date=? AND period=? AND status='scheduled' AND slot>? ORDER BY slot,id",(driver_id,target['delivery_date'],target['period'],target['slot'])))
        if not affected:
            raise LogicError('لا توجد شحنات مجدولة بعد هذه الشحنة في الفترة نفسها.')
        normal_end=660 if target['period']=='صباحي' else 960
        if any(s['slot']+minutes+SLOT>normal_end+60 for s in affected):
            raise LogicError('مدة التأخير أكبر من الوقت الاحتياطي (60 دقيقة). اختر مدة أقصر.')
        ids=[sh['id'] for sh in affected]
        placeholders=','.join('?' for _ in ids)
        others=list(db.execute("SELECT slot FROM shipments WHERE driver_id=? AND delivery_date=? AND slot IS NOT NULL AND status!='cancelled' AND id NOT IN ("+placeholders+")",(driver_id,target['delivery_date'],*ids)))
        for sh in affected:
            nxt=sh['slot']+minutes
            if any(nxt < other['slot']+SLOT and nxt+SLOT > other['slot'] for other in others):
                raise LogicError('التأخير يتعارض مع موعد آخر. اختر مدة أقل.')
        for sh in affected:
            db.execute('UPDATE shipments SET slot=NULL WHERE id=?',(sh['id'],))
        for sh in affected:
            nxt=sh['slot']+minutes
            db.execute('UPDATE shipments SET slot=? WHERE id=?',(nxt,sh['id']))
            _msg(db,sh['id'],'المندوب',f'تنبيه: تأخر المندوب {minutes} دقيقة. موعدك السابق {label(sh["slot"])}، وموعدك الجديد {label(nxt)}. نعتذر عن التأخير.')
        return len(affected)

def delay(driver_id,minutes,path=DB_PATH):
    if type(minutes) is not int or minutes not in [0,15,30,45,60]: raise LogicError('مدة التأخير غير صحيحة.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        day=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        rows=list(db.execute('SELECT * FROM shipments WHERE driver_id=? AND delivery_date=?',(driver_id,day)))
        if not rows: raise LogicError('انتقل إلى يوم التوصيل أولا.')
        old=db.execute('SELECT minutes FROM delays WHERE driver_id=? AND delivery_date=?',(driver_id,day)).fetchone()
        delta=minutes-(old['minutes'] if old else 0)
        if not delta: return
        booked=[r for r in rows if r['status']=='scheduled' and r['slot'] is not None]
        if any(s['slot']+delta<0 or s['slot']+delta+SLOT>1440 for s in booked):raise LogicError('التأخير يتجاوز اليوم.')
        for s in booked: db.execute('UPDATE shipments SET slot=? WHERE id=?',(-s['slot']-1,s['id']))
        for s in booked: db.execute('UPDATE shipments SET slot=? WHERE id=?',(s['slot']+delta,s['id']))
        db.execute('INSERT INTO delays VALUES (?,?,?) ON CONFLICT(driver_id,delivery_date) DO UPDATE SET minutes=excluded.minutes',(driver_id,day,minutes))
        for s in booked: _msg(db,s['id'],'المندوب',f'تنبيه: تم تحديث موعد التوصيل إلى {label(s["slot"]+delta)} بسبب تأخير المندوب. نعتذر عن الإزعاج.')

def deliver(driver_id,sid,path=DB_PATH):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh=db.execute('SELECT * FROM shipments WHERE id=? AND driver_id=?',(sid,driver_id)).fetchone()
        day=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        if not sh or sh['status']!='scheduled' or day!=sh['delivery_date']: raise LogicError('التسليم متاح يوم التوصيل للشحنات المحجوزة فقط.')
        db.execute("UPDATE shipments SET status='delivered' WHERE id=?",(sid,))
        _msg(db,sid,'المندوب','تم تسليم شحنتك بنجاح. يسعدنا تقييمك للخدمة.')

def rate(sid,stars,path=DB_PATH):
    if type(stars) is not int or stars not in range(1,6): raise LogicError('اختر تقييما صحيحا.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh=db.execute('SELECT * FROM shipments WHERE id=?',(sid,)).fetchone()
        if not sh or sh['status']!='delivered' or sh['rating']: raise LogicError('التقييم متاح بعد التسليم مرة واحدة.')
        db.execute('UPDATE shipments SET rating=? WHERE id=?',(stars,sid))
        _msg(db,sid,'العميل',f'تقييمي للخدمة: {stars} من 5.')
        _msg(db,sid,'النظام','شكرا لتقييمك!')

def advance(path=DB_PATH):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        day=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        day=(datetime.fromisoformat(day)+timedelta(days=1)).date().isoformat()
        db.execute("UPDATE settings SET value=? WHERE key='today'",(day,))
        return day

def reset(path=DB_PATH):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM support_tickets');db.execute('DELETE FROM messages');db.execute('DELETE FROM delays');db.execute('DELETE FROM shipments')
        db.execute("UPDATE settings SET value=? WHERE key='today'",(saudi_today(),))
        _seed(db)


def save_customer_note(sid, note, path=DB_PATH):
    """Keep a short delivery instruction with the shipment for the driver."""
    if type(sid) is not int:
        raise LogicError('رقم الشحنة غير صالح.')
    if not isinstance(note, str):
        raise LogicError('الملاحظة غير صالحة.')
    note = note.strip()
    if len(note) > 300:
        raise LogicError('الملاحظة يجب ألا تتجاوز 300 حرف.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh = db.execute('SELECT status, customer_note FROM shipments WHERE id=?', (sid,)).fetchone()
        if not sh:
            raise LogicError('الشحنة غير موجودة.')
        if sh['status'] == 'delivered':
            raise LogicError('لا يمكن تعديل الملاحظة بعد التسليم.')
        if sh['customer_note'] == note:
            return
        db.execute('UPDATE shipments SET customer_note=? WHERE id=?', (note, sid))
        if note:
            _msg(db, sid, 'العميل', 'ملاحظة للتوصيل: ' + note)
        else:
            _msg(db, sid, 'العميل', 'تم حذف ملاحظة التوصيل السابقة.')


def arrived(driver_id, sid, path=DB_PATH):
    """Send an arrival notification once; keep shipment scheduled."""
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        sh = db.execute(
            "SELECT * FROM shipments WHERE id=? AND driver_id=?",
            (sid, driver_id),
        ).fetchone()
        if not sh or sh["status"] != "scheduled":
            raise LogicError("إشعار الوصول متاح للشحنات المجدولة فقط.")
        day = db.execute(
            "SELECT value FROM settings WHERE key='today'"
        ).fetchone()[0]
        if day != sh["delivery_date"]:
            raise LogicError("يمكن إرسال إشعار الوصول في يوم التوصيل فقط.")
        already = db.execute(
            """SELECT 1 FROM messages WHERE shipment_id=? AND sender='المندوب'
               AND body='وصل مندوب التوصيل إلى موقع التسليم.' LIMIT 1""",
            (sid,),
        ).fetchone()
        if already:
            raise LogicError("أرسل إشعار الوصول مسبقا لهذه الشحنة.")
        _msg(db, sid, "المندوب", "وصل مندوب التوصيل إلى موقع التسليم.")


TICKET_CATEGORIES = (
    'تأخر موعد التوصيل', 'شحنتي لم تصل', 'استفسار عن سبب التأخير',
    'مشكلة في حجز أو تعديل الموعد', 'تعذر التواصل مع المندوب', 'أخرى'
)


def customer_state(sid, path=DB_PATH):
    """Only the selected shipment's information, never another customer's details."""
    whole = state(path)
    sh = next((s for s in whole['shipments'] if s['id'] == sid), None)
    if not sh:
        raise LogicError('الشحنة غير موجودة.')
    with connect(path) as db:
        tickets = [dict(x) for x in db.execute(
            'SELECT id,category,description,reply,status,created_at FROM support_tickets WHERE shipment_id=? ORDER BY id DESC',
            (sid,))]
    return {
        'today': whole['today'], 'shipment': sh,
        'messages': whole['messages'].get(str(sid), []),
        'slots': whole['slots'].get(str(sid), []),
        'reschedule_slots': whole['reschedule_slots'].get(str(sid), []),
        'tickets': tickets,
        'slot_minutes': SLOT,
    }


def driver_state(driver_id, path=DB_PATH):
    whole = state(path)
    driver = next((d for d in whole['drivers'] if d['id'] == driver_id), None)
    if driver is None:
        raise LogicError('المندوب غير موجود.')
    own = [s for s in whole['shipments'] if s['driver_id'] == driver_id and s['status'] in ('scheduled', 'delivered')]
    return {'today': whole['today'], 'driver': driver, 'shipments': own, 'slot_minutes': SLOT}


def create_ticket(sid, category, description, path=DB_PATH):
    if category not in TICKET_CATEGORIES:
        raise LogicError('اختر نوع مشكلة صحيحا.')
    if not isinstance(description, str) or len(description.strip()) > 500:
        raise LogicError('الوصف لا يتجاوز 500 حرف.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh=db.execute('SELECT * FROM shipments WHERE id=?',(sid,)).fetchone()
        if not sh: raise LogicError('الشحنة غير موجودة.')
        current = ('موعدك الحالي: '+label(sh['slot'])+'. ') if sh['slot'] is not None else 'لم يتم تأكيد موعد بعد. '
        if category in ('تأخر موعد التوصيل','شحنتي لم تصل','استفسار عن سبب التأخير'):
            reply = 'رد آلي تجريبي: تم استلام استفسارك. '+current+'يمكنك متابعة أحدث حالة للشحنة من هذه الصفحة.'
        else:
            reply = 'رد آلي تجريبي: تم تسجيل طلبك بنجاح، وسيظهر هنا في سجل التذاكر. لا يوجد موظف دعم حقيقي في المحاكاة.'
        cur=db.execute('INSERT INTO support_tickets(shipment_id,category,description,reply,status,created_at) VALUES (?,?,?,?,?,?)',
            (sid, category, description.strip(),reply,'جديدة',datetime.now().strftime('%Y-%m-%d %H:%M')))
        _msg(db,sid,'الدعم الآلي',f'تم إنشاء تذكرة الدعم TKT-{cur.lastrowid:04d}. {reply}')
        return {'ticket_no':f'TKT-{cur.lastrowid:04d}','reply':reply}


def next_ticket_status(sid, ticket_id, path=DB_PATH):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM support_tickets WHERE shipment_id=? AND id=?',(sid,ticket_id)).fetchone()
        if not row: raise LogicError('التذكرة غير موجودة.')
        statuses=['جديدة','قيد المعالجة','تم الحل']
        new=statuses[min(statuses.index(row['status'])+1,2)]
        db.execute('UPDATE support_tickets SET status=? WHERE id=?',(new,ticket_id))
        return new

def staff_tickets(path=DB_PATH):
    with connect(path) as db:
        return [dict(row) for row in db.execute("SELECT t.id,t.shipment_id,t.category,t.description,t.reply,t.status,t.created_at,s.client,s.area,s.slot,s.delivery_date FROM support_tickets t JOIN shipments s ON s.id=t.shipment_id ORDER BY t.id DESC")]

def staff_reply(ticket_id, status, reply, path=DB_PATH):
    if status not in ('جديدة','قيد المعالجة','تم الحل'):
        raise LogicError('حالة غير صحيحة.')
    if not isinstance(reply,str) or not reply.strip() or len(reply.strip())>600:
        raise LogicError('اكتب ردا لا يزيد عن 600 حرف.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        ticket=db.execute('SELECT * FROM support_tickets WHERE id=?',(ticket_id,)).fetchone()
        if not ticket:raise LogicError('التذكرة غير موجودة.')
        db.execute('UPDATE support_tickets SET status=?,reply=? WHERE id=?',(status,reply.strip(),ticket_id))
        _msg(db,ticket['shipment_id'],'الدعم الفني',f'تحديث تذكرة TKT-{ticket_id:04d}: {status}. {reply.strip()}')
