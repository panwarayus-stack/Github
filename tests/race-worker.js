import {openDB,reserve} from '../database/db.js';
const db=openDB(process.argv[2]);
try {reserve(db,Number(process.argv[3]),1,15,'USD');console.log('won')} catch {console.log('lost')}
db.close();
