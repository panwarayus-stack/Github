import os, json
from functools import wraps
import gradio as gr
from admin import backend as b

def pretty(value): return json.dumps(value,indent=2,ensure_ascii=False,default=str)
def safe(fn):
    @wraps(fn)
    def inner(*args,**kwargs):
        try: return fn(*args,**kwargs)
        except Exception as e: return f'Error: {type(e).__name__}: {e}'
    return inner

def actor(request: gr.Request): return request.username or 'dashboard'

def overview():
    return pretty({'statistics':b.query("SELECT (SELECT COUNT(*) FROM users) users,(SELECT COUNT(*) FROM inventory) listings,(SELECT COUNT(*) FROM inventory WHERE status='AVAILABLE') available,(SELECT COUNT(*) FROM inventory WHERE status='RESERVED') reserved,(SELECT COUNT(*) FROM orders) orders,(SELECT COUNT(*) FROM orders WHERE status IN ('PAYMENT_SUBMITTED','UNDER_REVIEW')) pending_review,(SELECT COUNT(*) FROM orders WHERE status='APPROVED') completed"),'revenue_by_currency':b.query("SELECT currency,SUM(price) amount_minor_units FROM orders WHERE status='APPROVED' GROUP BY currency"),'recent_orders':b.query('SELECT * FROM orders ORDER BY created_at DESC LIMIT 10'),'recent_users':b.query('SELECT * FROM users ORDER BY created_at DESC LIMIT 10'),'recent_actions':b.query('SELECT * FROM activity_logs ORDER BY id DESC LIMIT 10')})

def inventory(search,country,service,status,minp,maxp):
    return pretty(b.query("SELECT i.*,c.name country,s.name service FROM inventory i JOIN countries c ON c.iso=i.country_iso JOIN services s ON s.id=i.service_id WHERE (i.number LIKE ? OR CAST(i.id AS TEXT) LIKE ?) AND i.country_iso LIKE ? AND s.name LIKE ? AND i.status LIKE ? AND i.price BETWEEN ? AND ? ORDER BY i.id DESC LIMIT 500",(f'%{search}%',f'%{search}%',f'%{country.upper()}%',f'%{service}%',f'%{status.upper()}%',round(float(minp or 0)*100),round(float(maxp or 999999999)*100))))

def orders(search,status):
    return pretty(b.query("SELECT o.*,u.username,p.reference,p.status payment_status,p.refund_note FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN payments p ON p.order_id=o.id WHERE (o.id LIKE ? OR CAST(o.user_id AS TEXT) LIKE ? OR COALESCE(u.username,'') LIKE ?) AND o.status LIKE ? ORDER BY o.created_at DESC LIMIT 500",(f'%{search}%',f'%{search}%',f'%{search}%',f'%{status.upper()}%')))

def users(search): return pretty(b.query("SELECT u.*,COUNT(o.id) orders,SUM(CASE WHEN o.status='APPROVED' THEN 1 ELSE 0 END) completed FROM users u LEFT JOIN orders o ON o.user_id=u.id WHERE CAST(u.id AS TEXT) LIKE ? OR COALESCE(u.username,'') LIKE ? GROUP BY u.id ORDER BY u.created_at DESC LIMIT 500",(f'%{search}%',f'%{search}%')))

def analytics(): return pretty({'daily':b.query("SELECT substr(created_at,1,10) period,COUNT(*) orders FROM orders GROUP BY period ORDER BY period DESC LIMIT 90"),'weekly':b.query("SELECT strftime('%Y-%W',created_at) period,COUNT(*) orders FROM orders GROUP BY period ORDER BY period DESC LIMIT 52"),'monthly':b.query("SELECT substr(created_at,1,7) period,COUNT(*) orders FROM orders GROUP BY period ORDER BY period DESC LIMIT 24"),'revenue':b.query("SELECT currency,SUM(price) minor_units FROM orders WHERE status='APPROVED' GROUP BY currency"),'inventory_by_country':b.query('SELECT country_iso,status,COUNT(*) count FROM inventory GROUP BY country_iso,status'),'sales_by_country':b.query("SELECT i.country_iso,COUNT(*) count FROM orders o JOIN inventory i ON i.id=o.listing_id WHERE o.status='APPROVED' GROUP BY i.country_iso"),'sales_by_service':b.query("SELECT s.name,COUNT(*) count FROM orders o JOIN inventory i ON i.id=o.listing_id JOIN services s ON s.id=i.service_id WHERE o.status='APPROVED' GROUP BY s.name"),'customer_growth':b.query("SELECT substr(created_at,1,10) day,COUNT(*) users FROM users GROUP BY day ORDER BY day DESC LIMIT 90")})

def preview(text, file, service):
    if file:
        if os.path.getsize(file)>1_000_000: raise ValueError('Maximum file size is 1 MB')
        with open(file,'r',encoding='utf-8-sig') as f: text=f.read()
    r=b.run_import(text,int(service)); return pretty(r), text

def preview_safe(text,file,service):
    try: return preview(text,file,service)
    except Exception as e: return f'Error: {e}', ''

def commit(text,service,request:gr.Request): return pretty(b.import_commit(text,int(service),actor(request)))
def decide(order,action,note,request:gr.Request): return b.decision(order,action,actor(request),note)
def change(ident,action,value,request:gr.Request): return b.inventory_change(ident,action,value,actor(request))
def user_block(ident,action,request:gr.Request): return b.block(ident,action=='block',actor(request))
def do_backup(request:gr.Request): return b.backup(actor(request))
def send_broadcast(text,request:gr.Request): return b.broadcast(text,actor(request))

def create_dashboard():
    with gr.Blocks(title='Number Marketplace Admin',theme=gr.themes.Soft(primary_hue='indigo',neutral_hue='slate')) as demo:
        gr.Markdown('# Number Marketplace · Admin\nManual payment review only. Prices are stored in minor currency units. Never treat a screenshot as proof of payment.')
        with gr.Tab('Dashboard'):
            btn=gr.Button('Refresh overview',variant='primary'); out=gr.Code(language='json');btn.click(safe(overview),outputs=out);demo.load(safe(overview),outputs=out)
        with gr.Tab('Add number / import'):
            gr.Markdown('One listing per line: `+14155550123 / 80`. Paste or upload UTF-8 TXT, preview, then confirm. Country must be resolvable by the full numbering plan.')
            gr.File(value='examples/listings.txt', label='Download example TXT', interactive=False)
            lines=gr.Textbox(lines=8,label='Listings'); file=gr.File(label='TXT file (optional, max 1 MB)',file_types=['.txt'],type='filepath');service=gr.Number(value=1,precision=0,label='Service ID');preview_btn=gr.Button('Preview'); result=gr.Textbox(lines=12,label='Import report'); state=gr.State(''); preview_btn.click(preview_safe,[lines,file,service],[result,state]);confirm=gr.Button('Confirm import',variant='primary');confirm.click(safe(commit),[state,service],result)
        with gr.Tab('Inventory'):
            with gr.Row(): search=gr.Textbox(label='Number or ID');country=gr.Textbox(label='Country ISO');servicefilter=gr.Textbox(label='Service');status=gr.Textbox(label='Status')
            with gr.Row(): minp=gr.Number(label='Minimum price',value=0);maxp=gr.Number(label='Maximum price',value=999999999)
            btn=gr.Button('Search');results=gr.Code(language='json');btn.click(safe(inventory),[search,country,servicefilter,status,minp,maxp],results)
            with gr.Row(): ident=gr.Number(label='Listing ID',precision=0);action=gr.Dropdown(['price','disable','enable'],label='Action',value='price');value=gr.Textbox(label='New price (for price action)')
            save=gr.Button('Apply');msg=gr.Textbox(label='Result');save.click(safe(change),[ident,action,value],msg)
        with gr.Tab('Orders'):
            with gr.Row(): q=gr.Textbox(label='Order ID or customer');s=gr.Textbox(label='Status')
            btn=gr.Button('Search');output=gr.Code(language='json');btn.click(safe(orders),[q,s],output)
            oid=gr.Textbox(label='Order ID');action=gr.Dropdown(['review','approve','reject','cancel','refund'],value='review',label='Decision'); note=gr.Textbox(label='Refund note');btn=gr.Button('Apply decision',variant='primary');msg=gr.Textbox(label='Result');btn.click(safe(decide),[oid,action,note],msg)
            pic=gr.Image(label='Payment screenshot',type='pil'); show=gr.Button('View payment screenshot');show.click(b.telegram_photo,oid,pic)
        with gr.Tab('Users'):
            q=gr.Textbox(label='User ID or username');btn=gr.Button('Search');out=gr.Code(language='json');btn.click(safe(users),q,out)
            uid=gr.Textbox(label='User ID');action=gr.Dropdown(['block','unblock'],value='block');btn=gr.Button('Apply');msg=gr.Textbox();btn.click(safe(user_block),[uid,action],msg)
        with gr.Tab('Broadcast'):
            gr.Markdown('Preview first, then confirm. Delivery can take time; do not submit twice.')
            text=gr.Textbox(lines=5,label='Announcement'); preview_text=gr.Textbox(lines=5,label='Preview',interactive=False); confirmed=gr.State('');p=gr.Button('Preview');p.click(lambda t:(t,t),text,[preview_text,confirmed]);send=gr.Button('Confirm and send',variant='primary');msg=gr.Textbox(label='Delivery result');send.click(safe(send_broadcast),confirmed,msg)
        with gr.Tab('Statistics'):
            btn=gr.Button('Refresh');out=gr.Code(language='json');btn.click(safe(analytics),outputs=out)
        with gr.Tab('Storage and backups'):
            gr.Markdown('Backups are snapshots, not a transactional database. Store them on a configured persistent bucket mount; test restore independently.')
            btn=gr.Button('Create verified backup');msg=gr.Textbox();btn.click(safe(do_backup),outputs=msg)
            refresh=gr.Button('Backup history');out=gr.Code(language='json');refresh.click(lambda:pretty(b.query('SELECT * FROM backups ORDER BY id DESC LIMIT 100')),outputs=out)
        with gr.Tab('Activity logs'):
            btn=gr.Button('Refresh');out=gr.Code(language='json');btn.click(lambda:pretty(b.query('SELECT * FROM activity_logs ORDER BY id DESC LIMIT 200')),outputs=out)
    return demo
