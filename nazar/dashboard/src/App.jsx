import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ErrorBoundary from './components/ErrorBoundary';
import Sidebar from './components/Sidebar';
import Login from './pages/Login';
import Overview from './pages/Overview';
import Conversations from './pages/Conversations';
import ConversationDetail from './pages/ConversationDetail';
import Contacts from './pages/Contacts';
import Pipeline from './pages/Pipeline';
import Handoffs from './pages/Handoffs';
import Followups from './pages/Followups';
import Campaigns from './pages/Campaigns';
import Templates from './pages/Templates';
import Settings from './pages/Settings';
import KnowledgeBase from './pages/KnowledgeBase';
import Analytics from './pages/Analytics';
import Billing from './pages/Billing';
import Team from './pages/Team';
import Onboarding from './pages/Onboarding';
import Privacy from './pages/Privacy';
import Terms from './pages/Terms';
import Spinner from './components/ui/Spinner';

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
      <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/privacy" element={<PublicPage><Privacy /></PublicPage>} />
      <Route path="/terms" element={<PublicPage><Terms /></PublicPage>} />

      {/* Protected routes */}
      <Route path="/*" element={
        <AuthGuard>
          <div className="app-layout">
            <Sidebar />
            <main className="app-main">
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/conversations" element={<Conversations />} />
                <Route path="/conversations/:contactId" element={<ConversationDetail />} />
                <Route path="/contacts" element={<Contacts />} />
                <Route path="/pipeline" element={<Pipeline />} />
                <Route path="/handoffs" element={<Handoffs />} />
                <Route path="/followups" element={<Followups />} />
                <Route path="/campaigns" element={<Campaigns />} />
                <Route path="/broadcasts" element={<Navigate to="/campaigns" replace />} />
                <Route path="/templates" element={<Templates />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/knowledge" element={<KnowledgeBase />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/billing" element={<Billing />} />
                <Route path="/team" element={<Team />} />
                <Route path="/onboarding" element={<Onboarding />} />
                <Route path="/privacy" element={<Privacy />} />
                <Route path="/terms" element={<Terms />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </main>
          </div>
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
