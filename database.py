"""SQLite storage and scheduling for a local educational simulation."""
import hashlib
import math
import sqlite3
from datetime import timezone
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).with_name('smart_delivery.sqlite3')
SLOT = 12
AREAS = {'حي الروضة':(16.894,42.552),'حي النزهة':(16.920,42.568),'حي الشاطئ':(16.902,42.539),'حي السويس':(16.871,42.563),'حي المطار':(16.915,42.583),'حي الصفا':(16.885,42.583)}
DRIVERS = [('أحمد','حي الروضة','حي النزهة'),('خالد','حي الشاطئ','حي السويس'),('ياسر','حي المطار','حي الصفا')]
CLIENTS = [('عبدالله عسيري','حي الروضة',1,'صباحي'),('محمد الصميلي','حي الروضة',1,'صباحي'),('يحيى حكمي','حي النزهة',1,'مسائي'),('سعد القحطاني','حي الشاطئ',2,'صباحي'),('فيصل المالكي','حي السويس',2,'مسائي'),('سالم الدوسري','حي المطار',3,'صباحي'),('فهد الشهراني','حي الصفا',3,'مسائي')]

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
        if not db.execute('SELECT 1 FROM settings').fetchone(): db.execute('INSERT INTO settings VALUES (?,?)',('today',datetime.now().date().isoformat()))
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
        _msg(db,i,'النظام',f'مرحبًا {name.split()[0]}، شحنتك جاهزة للتوصيل غدًا في {area}. اختر الوقت المناسب من الخيارات المتاحة أدناه.')

def state(path=DB_PATH):
    with connect(path) as db:
        day=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        shipments=[dict(row) for row in db.execute('SELECT * FROM shipments ORDER BY id')]
        drivers=[dict(row) for row in db.execute('SELECT * FROM drivers ORDER BY id')]
        messages={str(s['id']):[dict(r) for r in db.execute('SELECT sender,body,created_at FROM messages WHERE shipment_id=? ORDER BY id',(s['id'],))] for s in shipments}
        delays=[dict(row) for row in db.execute('SELECT * FROM delays')]
        return {'today':day,'shipments':shipments,'drivers':drivers,'messages':messages,'delays':delays,'slots':{str(s['id']):available(db,s) for s in shipments if s['status']=='pending'}, 'reschedule_slots':{str(s['id']):reschedule_options(db,s) for s in shipments if s['status']=='scheduled'}}

def available(db,sh):
    start,end=(540,780) if sh['period']=='صباحي' else (960,1260)
    row=db.execute('SELECT minutes FROM delays WHERE driver_id=? AND delivery_date=?',(sh['driver_id'],sh['delivery_date'])).fetchone()
    offset=row['minutes'] if row else 0
    occupied={r['slot'] for r in db.execute("SELECT slot FROM shipments WHERE driver_id=? AND delivery_date=? AND slot IS NOT NULL AND status!='cancelled'",(sh['driver_id'],sh['delivery_date']))}
    return [{'minute':t+offset,'free':(t+offset) not in occupied} for t in range(start,end,SLOT) if t+offset+SLOT<=1380]

def book(sid,minute,path=DB_PATH):
    if type(minute) is not int: raise LogicError('اختر موعدًا صالحًا.')
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
        _msg(db,sid,'النظام',f'تم تأكيد موعدك بنجاح: {label(minute)}. شكرًا لتعاونك.')

def label(minute):
    def f(n): return f'{n//60:02d}:{n%60:02d}'
    return f'{f(minute)} – {f(minute+SLOT)}'

def _sim_now(db):
    """Saudi current time when the simulation day is real today."""
    saudi = timezone(timedelta(hours=3))
    real_now = datetime.now(saudi)
    day = db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
    if day == real_now.date().isoformat():
        return real_now
    return datetime.fromisoformat(day).replace(tzinfo=saudi)

def _five_hours_left(db, sh):
    saudi = timezone(timedelta(hours=3))
    delivery = datetime.fromisoformat(sh['delivery_date']).replace(tzinfo=saudi)
    delivery += timedelta(minutes=sh['slot'])
    return delivery - _sim_now(db) >= timedelta(hours=5)

def reschedule_options(db, sh):
    """Possible replacement slots; existing appointment remains reserved."""
    if sh['status'] != 'scheduled' or sh['rescheduled_count'] >= 1 or not _five_hours_left(db, sh):
        return []
    choices = available(db, sh)
    saudi = timezone(timedelta(hours=3))
    now = _sim_now(db)
    return [
        v for v in choices
        if v['free'] and v['minute'] != sh['slot']
        and datetime.fromisoformat(sh['delivery_date']).replace(tzinfo=saudi)
        + timedelta(minutes=v['minute']) - now >= timedelta(hours=5)
    ]

def reschedule(sid, minute, path=DB_PATH):
    """Single atomic change, once, five hours before both appointments."""
    if type(minute) is not int:
        raise LogicError('اختر موعدًا صحيحًا.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh = db.execute('SELECT * FROM shipments WHERE id=?', (sid,)).fetchone()
        if not sh or sh['status'] != 'scheduled':
            raise LogicError('هذه الشحنة غير قابلة لتعديل الموعد.')
        if sh['rescheduled_count'] >= 1:
            raise LogicError('استخدمت محاولة تغيير الموعد الوحيدة لهذه الشحنة.')
        if not _five_hours_left(db, sh):
            raise LogicError('يُسمح بالتغيير قبل الموعد بخمس ساعات على الأقل.')
        valid = {v['minute'] for v in reschedule_options(db, sh)}
        if minute not in valid:
            raise LogicError('الموعد الجديد غير متاح أو يقل عن خمس ساعات من الآن.')
        old_slot = sh['slot']
        try:
            db.execute(
                'UPDATE shipments SET slot=?, rescheduled_count=1 WHERE id=?',
                (minute, sid)
            )
        except sqlite3.IntegrityError as exc:
            raise LogicError('الموعد الجديد حُجز للتو، اختر موعدًا آخر.') from exc
        _msg(db, sid, 'العميل', f'طلبت تعديل الموعد من {label(old_slot)} إلى {label(minute)}.')
        _msg(db, sid, 'النظام', f'تم اعتماد الموعد الجديد: {label(minute)}. استُخدمت محاولة التعديل الوحيدة.')

def delay_from(driver_id, sid, minutes=15, path=DB_PATH):
    """Delay this customer and later bookings in the same driver/day/period."""
    if type(minutes) is not int or minutes not in (15, 30, 45, 60):
        raise LogicError('اختر تأخيرًا صحيحًا.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        day = db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        target = db.execute(
            'SELECT * FROM shipments WHERE id=? AND driver_id=?',
            (sid, driver_id)
        ).fetchone()
        if not target or target['status'] != 'scheduled' or target['delivery_date'] != day:
            raise LogicError('يمكن تسجيل التأخير لشحنة مجدولة في يوم توصيلها فقط.')
        affected = list(db.execute(
            """SELECT * FROM shipments
               WHERE driver_id=? AND delivery_date=?
                 AND period=? AND status='scheduled' AND slot>=?
               ORDER BY slot,id""",
            (driver_id, day, target['period'], target['slot'])
        ))
        if not affected:
            raise LogicError('لا توجد شحنات للتأخير.')
        if any(sh['slot'] + minutes + SLOT > 1380 for sh in affected):
            raise LogicError('التأخير يتجاوز نهاية جدول التوصيل.')
        ids = [sh['id'] for sh in affected]
        others = list(db.execute(
            """SELECT slot FROM shipments
               WHERE driver_id=? AND delivery_date=?
                 AND slot IS NOT NULL AND status!='cancelled'
                 AND id NOT IN ("""
            + ','.join('?' * len(ids)) + ')',
            [driver_id, day, *ids]
        ))
        for sh in affected:
            next_slot = sh['slot'] + minutes
            if any(
                next_slot < other['slot'] + SLOT
                and next_slot + SLOT > other['slot']
                for other in others
            ):
                raise LogicError('التأخير يتعارض مع موعد سابق أو فترة أخرى؛ لم تتغير المواعيد.')
        for sh in affected:
            db.execute(
                'UPDATE shipments SET slot=? WHERE id=?',
                (-sh['slot'] - 1, sh['id'])
            )
        for sh in affected:
            db.execute(
                'UPDATE shipments SET slot=? WHERE id=?',
                (sh['slot'] + minutes, sh['id'])
            )
            _msg(
                db, sh['id'], 'المندوب',
                f'تنبيه: تأخر المندوب {minutes} دقيقة. موعدك الجديد {label(sh["slot"] + minutes)}.'
            )
        return len(affected)

def delay(driver_id,minutes,path=DB_PATH):
    if type(minutes) is not int or minutes not in [0,15,30,45,60]: raise LogicError('مدة التأخير غير صحيحة.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        day=db.execute("SELECT value FROM settings WHERE key='today'").fetchone()[0]
        rows=list(db.execute('SELECT * FROM shipments WHERE driver_id=? AND delivery_date=?',(driver_id,day)))
        if not rows: raise LogicError('انتقل إلى يوم التوصيل أولًا.')
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
    if type(stars) is not int or stars not in range(1,6): raise LogicError('اختر تقييمًا صحيحًا.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh=db.execute('SELECT * FROM shipments WHERE id=?',(sid,)).fetchone()
        if not sh or sh['status']!='delivered' or sh['rating']: raise LogicError('التقييم متاح بعد التسليم مرة واحدة.')
        db.execute('UPDATE shipments SET rating=? WHERE id=?',(stars,sid))
        _msg(db,sid,'العميل',f'تقييمي للخدمة: {stars} من 5.')
        _msg(db,sid,'النظام','شكرًا لتقييمك!')

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
        db.execute('DELETE FROM messages')
        db.execute('DELETE FROM delays')
        db.execute('DELETE FROM shipments')
        db.execute("UPDATE settings SET value=? WHERE key='today'",(datetime.now().date().isoformat(),))
        _seed(db)

def save_customer_note(sid, note, path=DB_PATH):
    if type(sid) is not int:
        raise LogicError('رقم الشحنة غير صالح.')
    if not isinstance(note, str):
        raise LogicError('الملاحظة غير صالحة.')
    note = note.strip()
    if len(note) > 300:
        raise LogicError('الملاحظة يجب ألا تتجاوز 300 حرف.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        sh = db.execute(
            'SELECT status, customer_note FROM shipments WHERE id=?',
            (sid,)
        ).fetchone()
        if not sh:
            raise LogicError('الشحنة غير موجودة.')
        if sh['status'] == 'delivered':
            raise LogicError('لا يمكن تعديل الملاحظة بعد التسليم.')
        if sh['customer_note'] == note:
            return
        db.execute(
            'UPDATE shipments SET customer_note=? WHERE id=?',
            (note, sid)
        )
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
            raise LogicError("أُرسل إشعار الوصول مسبقًا لهذه الشحنة.")
        _msg(db, sid, "المندوب", "وصل مندوب التوصيل إلى موقع التسليم.")
