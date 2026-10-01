import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

// The reporting engine shares the dashboard origin and authenticates every API
// request through Mirai's existing auth backend. No credentials in frame URLs.
export default function SEO() {
  const location = useLocation();
  const navigate = useNavigate();
  const frame = useRef(null);
  const [initialSource] = useState(() => `/seo-dashboard/${location.search}${location.hash}`);
  useEffect(() => {
    const syncRoute = (event) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return;
      const route = event.data;
      if (route?.type !== 'mirai-seo-route' || typeof route.search !== 'string' || route.search.length > 2048 ||
          !/^#(sites|ecosystem|searches|visits|authority|connections)$/.test(route.hash)) return;
      navigate({ pathname: location.pathname, search: route.search, hash: route.hash }, { replace: true });
    };
    window.addEventListener('message', syncRoute);
    return () => window.removeEventListener('message', syncRoute);
  }, [navigate, location.pathname]);
  useEffect(() => {
    const target = new URL(`/seo-dashboard/${location.search}${location.hash}`, window.location.origin);
    const current = frame.current?.contentWindow?.location;
    if (current && current.href !== 'about:blank' && current.href !== target.href) frame.current.src = target.href;
  }, [location.search, location.hash]);
  return (
    <iframe
      ref={frame}
      title="Mirai SEO — Mirai Skin, Glow Coded and Rooted Glow"
      src={initialSource}
      className="w-full border-0 block h-[calc(100dvh-140px)] min-h-[420px] lg:h-[calc(100dvh-2px)] lg:min-h-[640px]"
      referrerPolicy="same-origin"
    />
  );
}
