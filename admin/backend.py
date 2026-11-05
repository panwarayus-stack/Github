import datetime, hashlib, os, sqlite3, subprocess, json, time
from pathlib import Path
import requests

DB = os.getenv('DATABASE_PATH', './data/marketplace.db')
BACKUPS = os.getenv('BACKUP_DIR', './data/backups')
TOKEN = os.getenv('BOT_TOKEN', '')

def connect():
    c=sqlite3.connect(DB, timeout=5)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=5000')
    return c

def query(sql, params=()):
    with connect() as c: return [dict(r) for r in c.execute(sql, params).fetchall()]

def audit(c, actor, action, kind, ident, before=None, after=None):
    c.execute('INSERT INTO activity_logs(admin_id,action,record_type,record_id,before_json,after_json) VALUES(?,?,?,?,?,?)', (actor,action,kind,str(ident),json.dumps(before,default=str),json.dumps(after,default=str)))

def run_import(lines, service, commit=False):
    if len(lines.encode('utf8'))>1_000_000: raise ValueError('Maximum import size is 1 MB')
    r=subprocess.run(['node','bot/import.js','commit' if commit else 'preview',str(int(service))],input=json.dumps({'lines':lines.splitlines()}),capture_output=True,text=True,timeout=60,check=True)
    return json.loads(r.stdout)

def import_commit(lines,service,actor):
    # Import is line-atomic; the audit records counts, not the uploaded numbers.
    r=run_import(lines,service,True)
    with connect() as c: audit(c,actor,'import','inventory','bulk',None,{k:r[k] for k in ('ok','skipped','failed')})
    return r

def decision(order_id,action,actor,note=''):
    transitions={'approve':({'PAYMENT_SUBMITTED','UNDER_REVIEW'},'APPROVED','SOLD','APPROVED'), 'reject':({'PAYMENT_SUBMITTED','UNDER_REVIEW'},'REJECTED','AVAILABLE','REJECTED'), 'cancel':({'PENDING_PAYMENT','PAYMENT_SUBMITTED','UNDER_REVIEW'},'CANCELLED','AVAILABLE','CANCELLED'), 'refund':({'APPROVED'},'REFUNDED','SOLD','REFUNDED'), 'review':({'PAYMENT_SUBMITTED'},'UNDER_REVIEW','RESERVED','SUBMITTED')}
    if action not in transitions: raise ValueError('Invalid decision')
    allowed,target,inv,pay=transitions[action]
    if action=='refund' and not note.strip(): raise ValueError('A refund record requires a note; money must be returned separately.')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM orders WHERE id=?',(order_id.strip(),)).fetchone()
        if not row or row['status'] not in allowed: raise ValueError('Order not found or transition is not allowed')
        if row['status']=='PENDING_PAYMENT' and row['expires_at'] <= datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'): raise ValueError('Order has expired')
        old=dict(row)
        c.execute("UPDATE orders SET status=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(target,row['id']))
        c.execute('UPDATE inventory SET status=? WHERE id=?',(inv,row['listing_id']))
        c.execute('UPDATE payments SET status=?,refund_note=? WHERE order_id=?',(pay,note.strip() if action=='refund' else None,row['id']))
        audit(c,actor,action,'order',row['id'],old,{'status':target,'note':note})
    # Decision is committed before notification; failure is explicit to the administrator.
    try:
        resp=requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',json={'chat_id':row['user_id'],'text':f'Order {row["id"]}: {target}.'},timeout=10)
        resp.raise_for_status()
        if not resp.json().get('ok'): raise ValueError('Telegram rejected notification')
        return f'{target}. Customer notified.'
    except Exception: return f'{target} saved, but notification failed. Contact the customer manually.'

def inventory_change(ident,action,value,actor):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE'); row=c.execute('SELECT * FROM inventory WHERE id=?',(int(ident),)).fetchone()
        if not row: raise ValueError('Listing not found')
        old=dict(row)
        if action=='price':
            from decimal import Decimal, InvalidOperation
            try:
                d=Decimal(value)
                if not d.is_finite() or d<0 or d.as_tuple().exponent < -2 or d>999999999: raise ValueError()
                cents=int(d*100)
            except (InvalidOperation,ValueError): raise ValueError('Invalid price')
            c.execute('UPDATE inventory SET price=? WHERE id=?',(cents,row['id']))
        elif action in ('disable','enable'):
            if row['status'] not in ('AVAILABLE','DISABLED'): raise ValueError('Cannot change a reserved or sold listing')
            c.execute('UPDATE inventory SET status=? WHERE id=?',('DISABLED' if action=='disable' else 'AVAILABLE',row['id']))
        else: raise ValueError('Unknown action')
        new=dict(c.execute('SELECT * FROM inventory WHERE id=?',(row['id'],)).fetchone()); audit(c,actor,action,'inventory',ident,old,new)
    return 'Saved.'

def block(user_id,blocked,actor):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE'); row=c.execute('SELECT * FROM users WHERE id=?',(int(user_id),)).fetchone()
        if not row: raise ValueError('User not found')
        c.execute('UPDATE users SET blocked=? WHERE id=?',(int(blocked),row['id'])); audit(c,actor,'block' if blocked else 'unblock','user',user_id,dict(row),{'blocked':blocked})
    return 'Saved.'

def backup(actor):
    Path(BACKUPS).mkdir(parents=True,exist_ok=True)
    name='marketplace-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite'
    path=Path(BACKUPS)/name
    if path.exists(): raise ValueError('Backup already exists')
    with connect() as src:
        dst=sqlite3.connect(str(path))
        try:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Backup integrity check failed')
        finally: dst.close()
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with connect() as c:
        c.execute('INSERT INTO backups(filename,sha256) VALUES(?,?)',(name,digest)); audit(c,actor,'backup','backup',name,None,{'sha256':digest})
    return f'Verified backup {name}\nSHA256 {digest}'

def telegram_photo(order_id):
    rows=query('SELECT file_id FROM payment_submissions WHERE order_id=? ORDER BY id DESC LIMIT 1',(order_id.strip(),))
    if not rows: raise ValueError('No payment screenshot found')
    r=requests.get(f'https://api.telegram.org/bot{TOKEN}/getFile',params={'file_id':rows[0]['file_id']},timeout=10);r.raise_for_status(); result=r.json()
    if not result.get('ok'): raise ValueError('Telegram could not retrieve this file')
    size=result['result'].get('file_size',0)
    if size>5_000_000: raise ValueError('Image exceeds size limit')
    r=requests.get(f'https://api.telegram.org/file/bot{TOKEN}/'+result['result']['file_path'],timeout=20);r.raise_for_status()
    if len(r.content)>5_000_000: raise ValueError('Image exceeds size limit')
    from PIL import Image
    from io import BytesIO
    image=Image.open(BytesIO(r.content)); image.load(); return image

def broadcast(text,actor):
    text=text.strip()
    if not text or len(text)>3500: raise ValueError('Message must be 1–3500 characters')
    users=query('SELECT id FROM users WHERE blocked=0 ORDER BY id')
    with connect() as c:
        cur=c.execute('INSERT INTO broadcasts(admin_id,message) VALUES(?,?)',(actor,text));bid=cur.lastrowid
        audit(c,actor,'broadcast','broadcast',bid,None,{'recipients':len(users)})
    ok=failed=0
    for user in users:
        try:
            for attempt in range(2):
                r=requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',json={'chat_id':user['id'],'text':text},timeout=10)
                data=r.json()
                if r.status_code==429 and attempt==0:
                    time.sleep(min(int(data.get('parameters',{}).get('retry_after',1)),60));continue
                if not r.ok or not data.get('ok'): raise ValueError('Delivery failed')
                break
            else: raise ValueError('Delivery failed')
            ok+=1
        except Exception: failed+=1
        # Persist progress so a restart does not silently report zero deliveries.
        with connect() as c: c.execute('UPDATE broadcasts SET successful=?,failed=? WHERE id=?',(ok,failed,bid))
        time.sleep(0.06)
    return f'Broadcast #{bid}: {ok} delivered, {failed} failed.'
