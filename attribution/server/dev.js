// Standalone loopback-only preview. Never imported by the production server.
import express from 'express';
import process, { loadEnvFile } from 'node:process';
import { createAttributionRouter } from './report.js';

if (process.env.MIRAI_ATTRIBUTION_ENV) loadEnvFile(process.env.MIRAI_ATTRIBUTION_ENV);
const app = express();
app.use('/attribution-api', createAttributionRouter({ authorize: (_req, _res, next) => next() }));
app.listen(5109, '127.0.0.1', () => console.log('Attribution preview API: http://127.0.0.1:5109'));
