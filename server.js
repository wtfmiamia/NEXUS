import express from 'express';
import fs       from 'fs';
import path     from 'path';
import crypto   from 'crypto';
import { exec, spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { promisify }     from 'util';

const __filename  = fileURLToPath(import.meta.url);
const __dirname   = path.dirname(__filename);
const execPromise = promisify(exec);

const app  = express();
const PORT = 4000;

const ROOT_PATH    = __dirname;
const DB_PATH      = path.join(ROOT_PATH, 'db.json');
const CONFIG_PATH  = path.join(ROOT_PATH, 'config.json');
const PUBLIC_PATH  = path.join(ROOT_PATH, 'public');

const visionExePath  = path.join(ROOT_PATH, 'src', 'vision.py');
const syncScriptPath = path.join(ROOT_PATH, 'src', 'lcu_sync.py');



//  Session Token. Generated once, stored in config.json.


function loadOrCreateConfig() {
    let cfg = {};
    try {
        if (fs.existsSync(CONFIG_PATH)) {
            cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
        }
    } catch { /* ignore parse errors */ }

    if (!cfg.nexusToken) {
        cfg.nexusToken = crypto.randomBytes(32).toString('hex');
        fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
        console.log(`[Auth] New session token generated. Share it with clients.`);
    }

    return cfg;
}

const CONFIG        = loadOrCreateConfig();
const SESSION_TOKEN = CONFIG.nexusToken;
console.log(`[Auth] Token: ${SESSION_TOKEN}`);


const ENC_KEY = crypto.createHash('sha256').update(SESSION_TOKEN).digest(); 

function encryptDB(plainObj) {
    const iv  = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', ENC_KEY, iv);
    const plain   = Buffer.from(JSON.stringify(plainObj), 'utf-8');
    const enc     = Buffer.concat([cipher.update(plain), cipher.final()]);
    const tag     = cipher.getAuthTag();
    return JSON.stringify({
        enc:  true,
        iv:   iv.toString('hex'),
        tag:  tag.toString('hex'),
        data: enc.toString('hex'),
    });
}

function decryptDB(raw) {
    const wrapper = JSON.parse(raw);
    if (!wrapper.enc) return wrapper;          

    const iv   = Buffer.from(wrapper.iv,   'hex');
    const tag  = Buffer.from(wrapper.tag,  'hex');
    const data = Buffer.from(wrapper.data, 'hex');

    const decipher = crypto.createDecipheriv('aes-256-gcm', ENC_KEY, iv);
    decipher.setAuthTag(tag);
    const plain = Buffer.concat([decipher.update(data), decipher.final()]);
    return JSON.parse(plain.toString('utf-8'));
}

function readDB() {
    try {
        if (!fs.existsSync(DB_PATH)) return [];
        const raw = fs.readFileSync(DB_PATH, 'utf-8').trim();
        if (!raw) return [];
        
        let db = decryptDB(raw);
        let needsMigration = false;

        db = db.map(acc => {
            if (acc.password && !acc.password.includes('"iv":')) {
                console.log(`[DB] Migrating plain-text password for: ${acc.username}`);
                
                const iv = crypto.randomBytes(12);
                const cipher = crypto.createCipheriv('aes-256-gcm', ENC_KEY, iv);
                const enc = Buffer.concat([cipher.update(Buffer.from(acc.password, 'utf-8')), cipher.final()]);
                const tag = cipher.getAuthTag();
                
                acc.password = JSON.stringify({
                    iv: iv.toString('hex'),
                    tag: tag.toString('hex'),
                    data: enc.toString('hex'),
                });
                needsMigration = true;
            }
            return acc;
        });

        if (needsMigration) {
            writeDB(db);
        }

        return db;
    } catch (e) {
        console.error(`[DB] Read error: ${e.message}`);
        return [];
    }
}

function writeDB(data) {
    fs.writeFileSync(DB_PATH, encryptDB(data));
}

const readConfig = () => {
    try {
        return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
    } catch { return {}; }
};
const writeConfig = (data) => fs.writeFileSync(CONFIG_PATH, JSON.stringify(data, null, 2));


app.use(express.json());
app.use(express.static(PUBLIC_PATH));



let lastDatabaseUpdate = Date.now();

function bumpUpdate() {
    lastDatabaseUpdate = Date.now();
}


const RIOT_PROCS = [
    'LeagueClient.exe',
    'RiotClientServices.exe',
    'LeagueCrashHandler.exe',
    'RiotClientCrashHandler.exe',
];

async function isRunning(proc) {
    try {
        const { stdout } = await execPromise(
            `tasklist /NH /FI "IMAGENAME eq ${proc}"`,
            { timeout: 3000 }
        );
        return stdout.toLowerCase().includes(proc.toLowerCase());
    } catch { return false; }
}

async function nukeRiotEcosystem() {
    // --- NEW CHECK START ---
    const clientRunning = await isRunning('RiotClientServices.exe');
    if (!clientRunning) {
        console.log(`[Nuke] Riot Client is not running. Skipping shutdown.`);
        return; 
    }

    console.log(`[Nuke] Graceful shutdown initiated...`);

    for (const proc of RIOT_PROCS) {
        if (await isRunning(proc)) {
            exec(`taskkill /IM "${proc}"`,
                { timeout: 3000 },
                () => { /* ignore errors */ }
            );
        }
    }

    await new Promise(r => setTimeout(r, 1500));

    for (const proc of RIOT_PROCS) {
        if (await isRunning(proc)) {
            console.log(`[Nuke] Force-killing ${proc}`);
            exec(`taskkill /F /IM "${proc}"`, { timeout: 3000 }, () => {});
        }
    }

    await new Promise(r => setTimeout(r, 1000));
    console.log(`[Nuke] Done.`);
}

function runSync(index) {
    return new Promise((resolve) => {
        const cmd = `python "${syncScriptPath}" "${index}"`;
        exec(cmd, { cwd: ROOT_PATH, timeout: 60000 }, (err, stdout, stderr) => {
            if (stdout) console.log(`[Sync] ${stdout.trim()}`);
            if (stderr) console.error(`[Sync Error] ${stderr.trim()}`);

            if (!err) {
                const db = readDB();
                if (db[index]) {
                    db[index].lastSync = Date.now();
                    writeDB(db);
                    bumpUpdate();
                    console.log(`[Sync] Account ${index} updated.`);
                }
            } else {
                console.error(`[Sync] Script error for index ${index}: ${err.message}`);
            }
            resolve(!err);
        });
    });
}


function startSyncWatcher(index) {
    console.log(`[Watcher] Waiting for LeagueClient.exe (index ${index})...`);
    let attempts  = 0;
    let triggered = false;

    const poll = setInterval(async () => {
        attempts++;

        if (!triggered) {
            const alive = await isRunning('LeagueClient.exe');
            if (alive) {
                triggered = true;
                clearInterval(poll);
                console.log(`[Watcher] League detected! Waiting 20s for lobby...`);
                setTimeout(() => runSync(index), 20000);
            }
        }

        if (attempts > 120) {           
            clearInterval(poll);
            console.log(`[Watcher] Timeout — League never appeared.`);
        }
    }, 5000);
}


let visionProcess = null;


app.get('/', (req, res) =>
    res.sendFile(path.join(PUBLIC_PATH, 'index.html'))
);

// Config
app.get('/api/config',  (req, res) => res.json(readConfig()));
app.post('/api/config', (req, res) => {
    const current = readConfig();
    // Never let the frontend overwrite the token
    writeConfig({ ...current, ...req.body, nexusToken: current.nexusToken });
    res.json({ success: true });
});

app.get('/api/token', (req, res) => {
    res.json({ token: SESSION_TOKEN });
});

app.use('/api', (req, res, next) => {
    const token = req.headers['x-nexus-token'];

    if (token !== SESSION_TOKEN) {
        return res.status(401).json({ error: 'Unauthorized' });
    }

    next();
});
// Accounts (read / create / update / delete)
app.get('/api/accounts', (req, res) => res.json(readDB()));

app.post('/api/accounts', (req, res) => {
    const db = readDB();
    const rawPassword = req.body.password || '';
    
    const pwIv        = crypto.randomBytes(12);
    const pwCipher    = crypto.createCipheriv('aes-256-gcm', ENC_KEY, pwIv);
    const pwEnc       = Buffer.concat([pwCipher.update(Buffer.from(rawPassword, 'utf-8')), pwCipher.final()]);
    const pwTag       = pwCipher.getAuthTag();
    const storedPassword = JSON.stringify({
        iv:   pwIv.toString('hex'),
        tag:  pwTag.toString('hex'),
        data: pwEnc.toString('hex'),
    });

    db.push({
        ...req.body,
        password: storedPassword,   // overwrite plain-text with encrypted form
        lastRank: 'UNRANKED',
        lp:       0,
        wins:     0,
        losses:   0,
        history:  [],
        topChamp: 0,
        tags:     req.body.tags  || '',
        notes:    req.body.notes || '',
    });
    writeDB(db);
    bumpUpdate();
    res.json({ success: true });
});

app.put('/api/accounts/:index', (req, res) => {
    const db  = readDB();
    const idx = parseInt(req.params.index, 10);
    if (idx < 0 || idx >= db.length)
        return res.status(404).json({ error: 'Account not found' });

    db[idx] = { ...db[idx], ...req.body };
    writeDB(db);
    bumpUpdate();
    res.json({ success: true });
});

app.delete('/api/accounts/:index', (req, res) => {
    const db  = readDB();
    const idx = parseInt(req.params.index, 10);
    if (idx < 0 || idx >= db.length)
        return res.status(404).json({ error: 'Account not found' });

    db.splice(idx, 1);
    writeDB(db);
    bumpUpdate();
    res.json({ success: true });
});

// Login sequence
app.post('/api/login', async (req, res) => {
    const { index } = req.body;

    if (visionProcess && !visionProcess.killed) {
        return res.status(409).json({ error: 'A login sequence is already in progress.' });
    }

    console.log(`\n[Login] Starting sequence for index ${index}...`);

    try {
        await nukeRiotEcosystem();

        console.log(`[Login] Launching vision.py for index ${index}...`);

        visionProcess = spawn('python', [visionExePath, index.toString()]);

        visionProcess.stdout.on('data', (chunk) => {
            const out = chunk.toString();
            console.log(`[Vision] ${out.trim()}`);
            
            if (out.includes('V_SIGNAL:LOGIN_SUBMITTED')) {
                console.log(`[Login] Vision done. Starting LCU watcher.`);
                startSyncWatcher(index);
            }
        });

        visionProcess.stderr.on('data', (chunk) => {
            const err = chunk.toString();
            if (!err.includes('libpng warning'))
                console.error(`[Vision Error] ${err.trim()}`);
        });

        visionProcess.on('exit', (code) => {
            console.log(`[Vision] Process exited (code ${code}).`);
            visionProcess = null;
        });

        res.json({ success: true, message: 'Authentication sequence initiated.' });

    } catch (err) {
        console.error(`[Login Error] ${err.message}`);
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/sync-only', async (req, res) => {
    const { index } = req.body;
    console.log(`[Sync] Manual sync for index ${index}`);
    res.json({ success: true, message: 'Sync started.' });
    await runSync(index);  
});

// Kill Riot
app.post('/api/kill-riot', async (req, res) => {
    await nukeRiotEcosystem();
    res.json({ success: true });
});

// Polling signal
app.get('/api/update-signal', (req, res) =>
    res.json({ lastUpdate: lastDatabaseUpdate })
);


app.listen(PORT, () => {
    console.log(`\n╔══════════════════════════════╗`);
    console.log(`║  NEXUS v5  →  localhost:${PORT}  ║`);
    console.log(`╚══════════════════════════════╝\n`);
});