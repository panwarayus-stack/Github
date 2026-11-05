import json, os, sqlite3, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'db.sqlite';os.environ['DATABASE_PATH']=str(self.db);os.environ['BACKUP_DIR']=str(Path(self.tmp.name)/'backups')
        subprocess.run(['node','bot/import.js','preview','1'],input='{"lines":[]}',text=True,check=True,capture_output=True)
        from admin import backend
        self.b=backend;backend.DB=str(self.db);backend.BACKUPS=os.environ['BACKUP_DIR']
        with backend.connect() as c: c.execute('INSERT INTO users(id,username) VALUES(1,?)',('alice',))
    def tearDown(self): self.tmp.cleanup()
    def test_import_preview_commit_and_backup_restore(self):
        lines='+14155550123 / 8\nnot a number\n+14155550123 / 9\n+14165550123 / 12'
        p=self.b.run_import(lines,1);self.assertEqual((p['ok'],p['skipped'],p['failed']),(2,1,1));self.assertEqual(self.b.query('SELECT * FROM inventory'),[])
        r=self.b.import_commit(lines,1,'admin');self.assertEqual((r['ok'],r['skipped'],r['failed']),(2,1,1))
        self.b.backup('admin'); backup=list(Path(self.b.BACKUPS).glob('*.sqlite'))[0]
        with sqlite3.connect(backup) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory').fetchone()[0],2)
            restored=Path(self.tmp.name)/'restored.sqlite'; dst=sqlite3.connect(restored);c.backup(dst);dst.close()
        with sqlite3.connect(restored) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory').fetchone()[0],2)
    def test_review_decisions_and_audit(self):
        self.b.run_import('+14155550123 / 8',1,True)
        with self.b.connect() as c:
            c.execute("UPDATE inventory SET status='RESERVED' WHERE id=1")
            c.execute("INSERT INTO orders(id,user_id,listing_id,price,currency,status,expires_at) VALUES('test',1,1,800,'USD','PAYMENT_SUBMITTED','2099-01-01T00:00:00.000Z')")
            c.execute("INSERT INTO payments(order_id,reference,status) VALUES('test','ABC','SUBMITTED')")
        response=Mock();response.json.return_value={'ok':True}
        with patch.object(self.b.requests,'post',return_value=response):
            self.assertIn('notified',self.b.decision('test','approve','admin'))
            with self.assertRaises(ValueError): self.b.decision('test','approve','admin')
            with self.assertRaises(ValueError): self.b.decision('test','refund','admin')
            self.b.decision('test','refund','admin','manual transfer recorded')
        self.assertEqual(self.b.query('SELECT status FROM inventory')[0]['status'],'SOLD')
        self.assertEqual(self.b.query('SELECT status FROM orders')[0]['status'],'REFUNDED')
        self.assertEqual(len(self.b.query('SELECT * FROM activity_logs')),2)
if __name__=='__main__': unittest.main()
