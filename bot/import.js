import { readFileSync } from 'node:fs';
import { openDB, parseListing, addListing } from '../database/db.js';
const mode=process.argv[2]; const service=Number(process.argv[3]||1); const data=JSON.parse(readFileSync(0,'utf8')); const db=openDB(process.env.DATABASE_PATH||'./data/marketplace.db');
if(!Array.isArray(data.lines)||data.lines.length>10000) throw Error('Too many lines');
let ok=0,skipped=0,failed=0;const results=[];const seen=new Set();
for(let index=0;index<data.lines.length;index++){const line=data.lines[index]; if(!line.trim())continue; try{const p=parseListing(line);if(seen.has(p.number)||db.prepare('SELECT id FROM inventory WHERE number=?').get(p.number)){skipped++;results.push(`Line ${index+1}: duplicate ${p.number}`);continue;}seen.add(p.number); if(mode==='commit')addListing(db,line,service); ok++;results.push(`Line ${index+1}: ${mode==='commit'?'imported':'valid'} ${p.number} (${p.iso}), ${(p.price/100).toFixed(2)}`);}catch(e){failed++;results.push(`Line ${index+1}: ${e.message}`);}}
console.log(JSON.stringify({ok,skipped,failed,results}));db.close();
