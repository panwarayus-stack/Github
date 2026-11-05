import os, subprocess, threading, time, signal, sys, sqlite3, fcntl
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()
import gradio as gr
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from admin.dashboard import create_dashboard

if os.getenv('ALLOW_UNSAFE_DEVELOPMENT') != '1':
    raise RuntimeError('Development build only. Read README.md and set ALLOW_UNSAFE_DEVELOPMENT=1 for local testing.')
user=os.getenv('DASHBOARD_USER',''); password=os.getenv('DASHBOARD_PASSWORD','')
if not user or len(password)<16: raise RuntimeError('Set DASHBOARD_USER and a DASHBOARD_PASSWORD of at least 16 characters')
# Install locked JS dependencies when deployed as a Gradio SDK Space.
if not Path('node_modules/telegraf').is_dir():
    subprocess.run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],check=True,timeout=180)
# Migrations run before either process opens the database.
init=subprocess.run(['node','bot/import.js','preview','1'],input='{"lines":[]}',text=True,capture_output=True)
if init.returncode: raise RuntimeError('Database initialization failed: '+init.stderr)
# Prevent duplicate workers on the same POSIX database host.
lock=open(os.getenv('DATABASE_PATH','./data/marketplace.db')+'.process.lock','w')
try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError: raise RuntimeError('A marketplace process is already running')
process=None; stop=threading.Event()
def supervisor():
    global process
    while not stop.is_set():
        process=subprocess.Popen(['node','bot/index.js'])
        while process.poll() is None and not stop.wait(1): pass
        if stop.is_set(): break
        print('Bot exited; retrying in 10 seconds',flush=True)
        stop.wait(10)
@asynccontextmanager
async def lifespan(app):
    thread=threading.Thread(target=supervisor,daemon=True);thread.start()
    yield
    stop.set()
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill();process.wait()
    thread.join(timeout=12)
app=FastAPI(lifespan=lifespan)
@app.get('/healthz')
def health():
    try:
        start=time.monotonic()
        with sqlite3.connect(os.getenv('DATABASE_PATH','./data/marketplace.db'),timeout=2) as c: c.execute('SELECT 1').fetchone()
        dbms=round((time.monotonic()-start)*1000,2)
        backup=Path(os.getenv('BACKUP_DIR','./data/backups'))
        storage=backup.is_dir() and os.access(backup,os.W_OK)
        bot=process is not None and process.poll() is None
        ok=bot and storage
        return JSONResponse({'status':'ok' if ok else 'degraded','database':'ok','backup_directory':'writable' if storage else 'unavailable','bot_process':'running' if bot else 'stopped','database_latency_ms':dbms},status_code=200 if ok else 503)
    except Exception: return JSONResponse({'status':'degraded','database':'unavailable'},status_code=503)
app=gr.mount_gradio_app(app,create_dashboard(),path='/',auth=(user,password),show_error=False,max_file_size='1mb')
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=int(os.getenv('PORT','7860')))
