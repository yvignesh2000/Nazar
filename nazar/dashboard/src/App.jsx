import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ErrorBoundary from './components/ErrorBoundary';
import NotificationProvider from './components/NotificationProvider';
import Sidebar from './components/Sidebar';
import Spinner from './components/ui/Spinner';

// Route-based code splitting — each page loads only when navigated to.
const Login = lazy(() => import('./pages/Login'));
const Overview = lazy(() => import('./pages/Overview'));
const Conversations = lazy(() => import('./pages/Conversations'));
const ConversationDetail = lazy(() => import('./pages/ConversationDetail'));
const Contacts = lazy(() => import('./pages/Contacts'));
const Campaigns = lazy(() => import('./pages/Campaigns'));
const Templates = lazy(() => import('./pages/Templates'));
const Settings = lazy(() => import('./pages/Settings'));
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase'));
const Analytics = lazy(() => import('./pages/Analytics'));
const Billing = lazy(() => import('./pages/Billing'));
const Team = lazy(() => import('./pages/Team'));
const Onboarding = lazy(() => import('./pages/Onboarding'));
const Privacy = lazy(() => import('./pages/Privacy'));
const Terms = lazy(() => import('./pages/Terms'));

/** Suspense wrapper for lazy-loaded routes */
function LazyRoute({ children }) {
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
}

function AuthGuard({ children }) {
  const { isAuthenticated, loading } = useAuth();

  if (loading) return <Spinner />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

function AppRoutes() {
  const { isAuthenticated, loading } = useAuth();

  if (loading) return <Spinner />;

  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LazyRoute><Login /></LazyRoute>} />
      <Route path="/privacy" element={<PublicPage><LazyRoute><Privacy /></LazyRoute></PublicPage>} />
      <Route path="/terms" element={<PublicPage><LazyRoute><Terms /></LazyRoute></PublicPage>} />

      {/* Protected routes */}
      <Route path="/*" element={
        <AuthGuard>
          <NotificationProvider>
          <div className="app-layout">
            <Sidebar />
            <main className="app-main">
              <Suspense fallback={<Spinner />}>
              <Routes>
                {/* Primary navigation */}
                <Route path="/" element={<Overview />} />
                <Route path="/inbox" element={<Conversations />} />
                <Route path="/inbox/:contactId" element={<ConversationDetail />} />
                <Route path="/contacts" element={<Contacts />} />
                <Route path="/campaigns" element={<Campaigns />} />
                <Route path="/reports" element={<Analytics />} />

                {/* Settings & Tools */}
                <Route path="/bot-setup" element={<Onboarding />} />
                <Route path="/knowledge" element={<KnowledgeBase />} />
                <Route path="/templates" element={<Templates />} />
                <Route path="/team" element={<Team />} />
                <Route path="/billing" element={<Billing />} />
                <Route path="/settings" element={<Settings />} />

                {/* Legacy redirects — keep old URLs working */}
                <Route path="/conversations" element={<Navigate to="/inbox" replace />} />
                <Route path="/conversations/:contactId" element={<Navigate to="/inbox/:contactId" replace />} />
                <Route path="/pipeline" element={<Navigate to="/contacts?view=pipeline" replace />} />
                <Route path="/handoffs" element={<Navigate to="/inbox?filter=escalated" replace />} />
                <Route path="/followups" element={<Navigate to="/inbox?filter=followups" replace />} />
                <Route path="/analytics" element={<Navigate to="/reports" replace />} />
                <Route path="/onboarding" element={<Navigate to="/bot-setup" replace />} />
                <Route path="/broadcasts" element={<Navigate to="/campaigns" replace />} />

                {/* Legal (also accessible from sidebar) */}
                <Route path="/privacy" element={<Privacy />} />
                <Route path="/terms" element={<Terms />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
              </Suspense>
            </main>
          </div>
          </NotificationProvider>
        </AuthGuard>
      } />
    </Routes>
  );
}

/** Legal pages accessible without sidebar when not logged in */
function PublicPage({ children }) {
  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '2rem' }}>
      {children}
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <ErrorBoundary>
            <AppRoutes />
          </ErrorBoundary>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
