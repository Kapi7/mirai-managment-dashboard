import { lazy, Suspense } from 'react';
import Layout from "./Layout.jsx";
import { BrowserRouter as Router, Route, Routes, useLocation, Navigate } from 'react-router-dom';
import { Skeleton } from "@/components/ui/skeleton";
import { AuthProvider, useAuth } from '@/contexts/AuthContext';

// Lazy load pages for faster initial load
const Reports = lazy(() => import('./Reports'));
const Pricing = lazy(() => import('./Pricing'));
const KorealyProcessor = lazy(() => import('./KorealyProcessor'));
const Settings = lazy(() => import('./Settings'));
const Login = lazy(() => import('./Login'));
const UserManagement = lazy(() => import('./UserManagement'));
const Support = lazy(() => import('./Support'));
const Tracking = lazy(() => import('./Tracking'));
const Activity = lazy(() => import('./Activity'));
const Marketing = lazy(() => import('./Marketing'));
const BlogCreator = lazy(() => import('./BlogCreator'));

// Protected route wrapper
function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return <PageLoading />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

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

    Pricing: Pricing,

    KorealyProcessor: KorealyProcessor,

    Settings: Settings,

    UserManagement: UserManagement,

    Support: Support,

    Activity: Activity,

    Marketing: Marketing,

    BlogCreator: BlogCreator,

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
    const { isAuthenticated } = useAuth();
    const currentPage = _getCurrentPage(location.pathname);

    // Login page doesn't need layout
    if (location.pathname === '/login') {
        return (
            <Suspense fallback={<PageLoading />}>
                <Routes>
                    <Route path="/login" element={<Login />} />
                </Routes>
            </Suspense>
        );
    }

    return (
        <Layout currentPageName={currentPage}>
            <Suspense fallback={<PageLoading />}>
                <Routes>
                    <Route path="/" element={<ProtectedRoute><Reports /></ProtectedRoute>} />
                    <Route path="/Reports" element={<ProtectedRoute><Reports /></ProtectedRoute>} />
                    <Route path="/Pricing" element={<ProtectedRoute><Pricing /></ProtectedRoute>} />
                    <Route path="/KorealyProcessor" element={<ProtectedRoute><KorealyProcessor /></ProtectedRoute>} />
                    <Route path="/Settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
                    <Route path="/UserManagement" element={<ProtectedRoute><UserManagement /></ProtectedRoute>} />
                    <Route path="/Support" element={<ProtectedRoute><Support /></ProtectedRoute>} />
                    <Route path="/Tracking" element={<ProtectedRoute><Tracking /></ProtectedRoute>} />
                    <Route path="/Activity" element={<ProtectedRoute><Activity /></ProtectedRoute>} />
                    <Route path="/Marketing" element={<ProtectedRoute><Marketing /></ProtectedRoute>} />
                    <Route path="/BlogCreator" element={<ProtectedRoute><BlogCreator /></ProtectedRoute>} />
                    <Route path="/login" element={<Login />} />
                </Routes>
            </Suspense>
        </Layout>
    );
}

export default function Pages() {
    return (
        <Router>
            <AuthProvider>
                <PagesContent />
            </AuthProvider>
        </Router>
    );
}