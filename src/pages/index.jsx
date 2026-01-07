import { lazy, Suspense } from 'react';
import Layout from "./Layout.jsx";
import { BrowserRouter as Router, Route, Routes, useLocation } from 'react-router-dom';
import { Skeleton } from "@/components/ui/skeleton";

// Lazy load pages for faster initial load
const Reports = lazy(() => import('./Reports'));
const KorealyProcessor = lazy(() => import('./KorealyProcessor'));
const Settings = lazy(() => import('./Settings'));

// Loading component
function PageLoading() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-8 w-[300px]" />
      <Skeleton className="h-[400px] w-full" />
    </div>
  );
}

const PAGES = {

    Reports: Reports,

    KorealyProcessor: KorealyProcessor,

    Settings: Settings,

}

function _getCurrentPage(url) {
    if (url.endsWith('/')) {
        url = url.slice(0, -1);
    }
    let urlLastPart = url.split('/').pop();
    if (urlLastPart.includes('?')) {
        urlLastPart = urlLastPart.split('?')[0];
    }

    const pageName = Object.keys(PAGES).find(page => page.toLowerCase() === urlLastPart.toLowerCase());
    return pageName || Object.keys(PAGES)[0];
}

// Create a wrapper component that uses useLocation inside the Router context
function PagesContent() {
    const location = useLocation();
    const currentPage = _getCurrentPage(location.pathname);
    
    return (
        <Layout currentPageName={currentPage}>
            <Suspense fallback={<PageLoading />}>
                <Routes>

                    <Route path="/" element={<Reports />} />

                    <Route path="/Reports" element={<Reports />} />

                    <Route path="/KorealyProcessor" element={<KorealyProcessor />} />

                    <Route path="/Settings" element={<Settings />} />

                </Routes>
            </Suspense>
        </Layout>
    );
}

export default function Pages() {
    return (
        <Router>
            <PagesContent />
        </Router>
    );
}