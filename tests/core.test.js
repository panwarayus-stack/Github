import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { openDB, parseListing, addListing, reserve, submitPayment, expire } from '../database/db.js';
function setup(){const dir=mkdtempSync(join(tmpdir(),'market-'));const db=openDB(join(dir,'db.sqlite'));db.prepare('INSERT INTO users(id) VALUES(1),(2)').run();return {db,done(){db.close();rmSync(dir,{recursive:true,force:true})}};}
test('detects full numbering plan and rejects malformed or invalid',()=>{assert.equal(parseListing('+14155550123 / 80').iso,'US');assert.equal(parseListing('+14165550123 / 10.50').iso,'CA');assert.equal(parseListing('+74951234567 / 2').iso,'RU');assert.equal(parseListing('+77273123456 / 2').iso,'KZ');assert.throws(()=>parseListing('4155550123 / 80'));assert.throws(()=>parseListing('+123 / 4'));assert.throws(()=>parseListing('+14155550123 / 1.234'));});
test('duplicate inventory, transactional reservation and duplicate callback',()=>{let {db,done}=setup();try{addListing(db,'+14155550123 / 80');assert.throws(()=>addListing(db,'+14155550123 / 90'));const o=reserve(db,1,1,15,'USD');assert.equal(o.listing.price,8000);assert.throws(()=>reserve(db,2,1,15,'USD'));assert.equal(db.prepare('SELECT COUNT(*) n FROM orders').get().n,1);assert.equal(db.prepare('SELECT status FROM inventory').get().status,'RESERVED');}finally{done()}});
test('payment submissions are unique and expiration releases inventory',()=>{let {db,done}=setup();try{addListing(db,'+14155550123 / 80');addListing(db,'+14165550123 / 10');let a=reserve(db,1,1,15,'USD');let b=reserve(db,2,2,15,'USD');submitPayment(db,1,a.id,'ref1','file','unique');assert.throws(()=>submitPayment(db,2,b.id,'ref1','another','different'));assert.equal(db.prepare('SELECT status FROM orders WHERE id=?').get(b.id).status,'PENDING_PAYMENT');assert.throws(()=>submitPayment(db,2,b.id,'ref2','another','unique'));db.prepare("UPDATE orders SET expires_at='2000-01-01T00:00:00.000Z' WHERE id=?").run(b.id);assert.equal(expire(db),1);assert.equal(db.prepare('SELECT status FROM inventory WHERE id=2').get().status,'AVAILABLE');assert.equal(db.prepare('SELECT status FROM orders WHERE id=?').get(a.id).status,'PAYMENT_SUBMITTED');}finally{done()}});
test('simultaneous processes cannot reserve the same number',async()=>{
 const {spawn}=await import('node:child_process');const dir=mkdtempSync(join(tmpdir(),'market-race-'));const path=join(dir,'db.sqlite');const db=openDB(path);
 try{db.prepare('INSERT INTO users(id) VALUES(1),(2)').run();addListing(db,'+14155550123 / 10');
 const run=(id)=>new Promise((resolve,reject)=>{const child=spawn(process.execPath,['tests/race-worker.js',path,String(id)]);let out='';child.stdout.on('data',v=>out+=v);child.on('error',reject);child.on('close',code=>code===0?resolve(out.trim()):reject(new Error(`worker ${code}`)));});
 const results=await Promise.all([run(1),run(2)]);assert.deepEqual(results.sort(),['lost','won']);assert.equal(db.prepare('SELECT COUNT(*) n FROM orders').get().n,1);
 }finally{db.close();rmSync(dir,{recursive:true,force:true});}
});
test('changed price cannot be silently charged after confirmation',()=>{const {db,done}=setup();try{addListing(db,'+14155550123 / 8');db.prepare('UPDATE inventory SET price=900 WHERE id=1').run();assert.throws(()=>reserve(db,1,1,15,'USD',800));assert.equal(db.prepare('SELECT status FROM inventory').get().status,'AVAILABLE');assert.equal(db.prepare('SELECT COUNT(*) n FROM orders').get().n,0);}finally{done()}});
