import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Overview from './pages/Overview';
import Conversations from './pages/Conversations';
import ConversationDetail from './pages/ConversationDetail';
import Contacts from './pages/Contacts';
import Pipeline from './pages/Pipeline';
import Handoffs from './pages/Handoffs';
import Followups from './pages/Followups';
import Broadcasts from './pages/Broadcasts';
import Templates from './pages/Templates';
import Settings from './pages/Settings';
import KnowledgeBase from './pages/KnowledgeBase';

export default function App() {
  return (
    <BrowserRouter>
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
            <Route path="/broadcasts" element={<Broadcasts />} />
            <Route path="/templates" element={<Templates />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/knowledge" element={<KnowledgeBase />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
