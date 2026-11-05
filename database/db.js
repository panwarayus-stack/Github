import { DatabaseSync } from 'node:sqlite';
import { readFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import { parsePhoneNumberFromString } from 'libphonenumber-js/max';

export function openDB(path) {
  mkdirSync(dirname(path), {recursive:true});
  const db = new DatabaseSync(path);
  db.exec('PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA journal_mode=DELETE;');
  db.exec(readFileSync(new URL('./schema.sql', import.meta.url), 'utf8'));
  return db;
}
export function tx(db, fn) { db.exec('BEGIN IMMEDIATE'); try { const result=fn(); db.exec('COMMIT'); return result; } catch(e) { db.exec('ROLLBACK'); throw e; } }
export function parseListing(line) {
  const match = /^\s*(\+\d{7,15})\s*\/\s*(\d{1,9}(?:\.\d{1,2})?)\s*$/.exec(line);
  if (!match) throw new Error('Expected +internationalnumber / price (up to two decimals)');
  const phone = parsePhoneNumberFromString(match[1]);
  if (!phone || !phone.isValid() || !phone.country) throw new Error('Invalid number or country cannot be resolved');
  const parts=match[2].split('.'); const price=Number(parts[0])*100+Number((parts[1]||'').padEnd(2,'0'));
  return {number:phone.number, iso:phone.country, callingCode:phone.countryCallingCode, country:new Intl.DisplayNames(['en'],{type:'region'}).of(phone.country), price};
}
export function addListing(db,line,service=1) {
  const p=parseListing(line);
  return tx(db,()=>{ db.prepare('INSERT OR IGNORE INTO countries(iso,name,calling_code) VALUES(?,?,?)').run(p.iso,p.country,p.callingCode); return db.prepare('INSERT INTO inventory(number,country_iso,calling_code,service_id,price) VALUES(?,?,?,?,?)').run(p.number,p.iso,p.callingCode,service,p.price); });
}
export function expire(db) {
  return tx(db,()=>{const rows=db.prepare("SELECT id,listing_id FROM orders WHERE status='PENDING_PAYMENT' AND expires_at<=strftime('%Y-%m-%dT%H:%M:%fZ','now')").all(); for(const r of rows){db.prepare("UPDATE orders SET status='EXPIRED',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?").run(r.id); db.prepare("UPDATE inventory SET status='AVAILABLE' WHERE id=? AND status='RESERVED'").run(r.listing_id);} return rows.length;});
}
export function reserve(db,user,id,minutes,currency,expectedPrice) {
  return tx(db,()=>{
    const listing=db.prepare("SELECT i.* FROM inventory i JOIN services s ON s.id=i.service_id WHERE i.id=? AND i.status='AVAILABLE' AND s.enabled=1").get(id);
    if(!listing) throw new Error('This listing is no longer available.');
    if(expectedPrice !== undefined && listing.price !== expectedPrice) throw new Error('Price changed; please review the listing again.');
    const changed=db.prepare("UPDATE inventory SET status='RESERVED' WHERE id=? AND status='AVAILABLE'").run(id);
    if(!changed.changes) throw new Error('This listing is no longer available.');
    const order=randomUUID(); const expires=new Date(Date.now()+minutes*60000).toISOString();
    db.prepare("INSERT INTO orders(id,user_id,listing_id,price,currency,status,expires_at) VALUES(?,?,?,?,?,'PENDING_PAYMENT',?)").run(order,user,id,listing.price,currency,expires);
    return {id:order,expires,listing};
  });
}
export function submitPayment(db,user,order,reference,fileId,uniqueId) {
 return tx(db,()=>{const o=db.prepare("SELECT * FROM orders WHERE id=? AND user_id=? AND status='PENDING_PAYMENT' AND expires_at>strftime('%Y-%m-%dT%H:%M:%fZ','now')").get(order,user); if(!o) throw new Error('Order expired or is not awaiting payment.');
  db.prepare("INSERT INTO payments(order_id,reference,status) VALUES(?,?,'SUBMITTED')").run(order,reference.toUpperCase());
  db.prepare('INSERT INTO payment_submissions(order_id,file_id,file_unique_id) VALUES(?,?,?)').run(order,fileId,uniqueId);
  db.prepare("UPDATE orders SET status='PAYMENT_SUBMITTED',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?").run(order); return o;});
}
