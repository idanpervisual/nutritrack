require('dotenv').config();
const express = require('express');
const Database = require('better-sqlite3');
const multer = require('multer');
const Anthropic = require('@anthropic-ai/sdk');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

// DB setup
const db = new Database(path.join(__dirname, 'nutrition.db'));
db.exec(`
  CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT DEFAULT 'Me',
    current_weight REAL,
    target_weight REAL,
    daily_calories INTEGER DEFAULT 2000,
    daily_protein INTEGER DEFAULT 150,
    daily_carbs INTEGER DEFAULT 200,
    daily_fat INTEGER DEFAULT 65
  );

  CREATE TABLE IF NOT EXISTS meal_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    meal_name TEXT NOT NULL,
    calories REAL DEFAULT 0,
    protein REAL DEFAULT 0,
    carbs REAL DEFAULT 0,
    fat REAL DEFAULT 0,
    photo_used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS weight_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    weight REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
  );
`);

// Multer — memory storage for photos (no disk writes needed)
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 10 * 1024 * 1024 }, // 10MB
});

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ─── Profile ────────────────────────────────────────────────────────────────

app.get('/api/profile', (req, res) => {
  const row = db.prepare('SELECT * FROM profile WHERE id = 1').get();
  res.json(row || {});
});

app.post('/api/profile', (req, res) => {
  const { name, current_weight, target_weight, daily_calories, daily_protein, daily_carbs, daily_fat } = req.body;
  db.prepare(`
    INSERT INTO profile (id, name, current_weight, target_weight, daily_calories, daily_protein, daily_carbs, daily_fat)
    VALUES (1, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      current_weight = excluded.current_weight,
      target_weight = excluded.target_weight,
      daily_calories = excluded.daily_calories,
      daily_protein = excluded.daily_protein,
      daily_carbs = excluded.daily_carbs,
      daily_fat = excluded.daily_fat
  `).run(name, current_weight, target_weight, daily_calories, daily_protein, daily_carbs, daily_fat);
  res.json({ ok: true });
});

// ─── Meal Logs ───────────────────────────────────────────────────────────────

app.get('/api/logs', (req, res) => {
  const date = req.query.date || new Date().toISOString().slice(0, 10);
  const rows = db.prepare('SELECT * FROM meal_logs WHERE date = ? ORDER BY time ASC').all(date);
  res.json(rows);
});

app.post('/api/logs', (req, res) => {
  const { meal_name, calories, protein, carbs, fat, photo_used } = req.body;
  const now = new Date();
  const date = now.toISOString().slice(0, 10);
  const time = now.toTimeString().slice(0, 5);
  const result = db.prepare(`
    INSERT INTO meal_logs (date, time, meal_name, calories, protein, carbs, fat, photo_used)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `).run(date, time, meal_name, calories || 0, protein || 0, carbs || 0, fat || 0, photo_used ? 1 : 0);
  res.json({ id: result.lastInsertRowid, ok: true });
});

app.delete('/api/logs/:id', (req, res) => {
  db.prepare('DELETE FROM meal_logs WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

// ─── Weight Logs ─────────────────────────────────────────────────────────────

app.get('/api/weight', (req, res) => {
  const rows = db.prepare('SELECT * FROM weight_logs ORDER BY date DESC LIMIT 30').all();
  res.json(rows);
});

app.post('/api/weight', (req, res) => {
  const { weight } = req.body;
  const date = new Date().toISOString().slice(0, 10);
  db.prepare('INSERT INTO weight_logs (date, weight) VALUES (?, ?)').run(date, weight);
  // Also update profile current weight
  db.prepare('UPDATE profile SET current_weight = ? WHERE id = 1').run(weight);
  res.json({ ok: true });
});

// ─── Photo Analysis ──────────────────────────────────────────────────────────

app.post('/api/analyze', upload.single('photo'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No photo provided' });
  if (!process.env.ANTHROPIC_API_KEY) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not set' });

  try {
    const base64 = req.file.buffer.toString('base64');
    const mediaType = req.file.mimetype;

    const message = await anthropic.messages.create({
      model: 'claude-opus-4-6',
      max_tokens: 512,
      messages: [
        {
          role: 'user',
          content: [
            {
              type: 'image',
              source: { type: 'base64', media_type: mediaType, data: base64 },
            },
            {
              type: 'text',
              text: `Analyze this image. It may be a meal/food, a nutrition label, or a product package.
Extract nutritional information and return ONLY a JSON object with these exact keys:
{
  "meal_name": "short descriptive name",
  "calories": number,
  "protein": number (grams),
  "carbs": number (grams),
  "fat": number (grams),
  "confidence": "high" | "medium" | "low",
  "note": "optional short note about estimation"
}
If it's a nutrition label, read the values directly (per serving). If it's a meal photo, estimate based on what you see.
Return ONLY the JSON, no other text.`,
            },
          ],
        },
      ],
    });

    const text = message.content[0].text.trim();
    const json = JSON.parse(text);
    res.json(json);
  } catch (err) {
    console.error('Analysis error:', err);
    res.status(500).json({ error: 'Failed to analyze photo', detail: err.message });
  }
});

// ─── Daily Summary ───────────────────────────────────────────────────────────

app.get('/api/summary', (req, res) => {
  const date = req.query.date || new Date().toISOString().slice(0, 10);
  const row = db.prepare(`
    SELECT
      COALESCE(SUM(calories), 0) as calories,
      COALESCE(SUM(protein), 0) as protein,
      COALESCE(SUM(carbs), 0) as carbs,
      COALESCE(SUM(fat), 0) as fat,
      COUNT(*) as meal_count
    FROM meal_logs WHERE date = ?
  `).get(date);
  res.json(row);
});

// Fallback to index.html for PWA routing
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`Nutrition Tracker running at http://localhost:${PORT}`);
});
