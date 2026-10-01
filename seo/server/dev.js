import express from 'express';
import { createSeoRouter } from './router.js';

// Separate loopback-only preview entry point. Production imports router.js,
// never this development authorization hook.
const app = express();
app.use('/seo-dashboard', createSeoRouter({ authorize: (req, _res, next) => {
  req.seoUser = { email: 'local@dev', is_admin: true }; next();
} }));
app.listen(5106, '127.0.0.1', () => console.log('Mirai SEO preview: http://127.0.0.1:5106/seo-dashboard/'));
