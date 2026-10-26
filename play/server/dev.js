// Standalone loopback-only preview. Never imported by the production server.
import express from 'express';
import process, { loadEnvFile } from 'node:process';
import { createPlayRouter } from './report.js';

if (process.env.MIRAI_PLAY_ENV) loadEnvFile(process.env.MIRAI_PLAY_ENV);
const app = express();
app.use('/play-api', createPlayRouter({ authorize: (_req, _res, next) => next() }));
app.listen(5111, '127.0.0.1', () => console.log('Play preview API: http://127.0.0.1:5111/play-api'));
