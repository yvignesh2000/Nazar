import { useState, useEffect, useRef } from 'react';
import { BookOpen, Save, Upload, Trash2, FileText, File, Plus, X } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { kb as kbApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import './KnowledgeBase.css';

const DOC_TYPE_ICONS = {
  text: '📄', markdown: '📝', pdf: '📕', csv: '📊',
};

export default function KnowledgeBase() {
  const [tab, setTab] = useState('documents');

  // Documents tab
  const { data: docsData, loading: docsLoading, refetch: refetchDocs } = useApi(
    () => kbApi.listDocuments(), []
  );
  const [uploading, setUploading] = useState(false);
  const [showAddText, setShowAddText] = useState(false);
  const [newDocTitle, setNewDocTitle] = useState('');
  const [newDocContent, setNewDocContent] = useState('');
  const [addingText, setAddingText] = useState(false);
  const fileInputRef = useRef(null);

  // Quick edit tab (legacy single textarea)
  const { data: legacyData, loading: legacyLoading, refetch: refetchLegacy } = useApi(
    () => kbApi.get(), [], { enabled: tab === 'quick-edit' }
  );
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (legacyData?.content !== undefined) setContent(legacyData.content);
  }, [legacyData]);

  const documents = docsData?.documents || [];

  async function handleFileUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    const ext = file.name.split('.').pop().toLowerCase();
    if (!['txt', 'md', 'pdf', 'csv'].includes(ext)) {
      alert('Unsupported file type. Allowed: .txt, .md, .pdf, .csv');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      alert('File too large (max 5MB)');
      return;
    }

    setUploading(true);
    try {
      await kbApi.uploadFile(file, file.name);
      refetchDocs();
    } catch (err) {
      alert('Upload failed: ' + (err.message || err));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleAddText() {
    if (!newDocTitle.trim() || !newDocContent.trim()) return;
    setAddingText(true);
    try {
      await kbApi.addDocument({
        title: newDocTitle.trim(),
        content: newDocContent.trim(),
        type: 'text',
        scope: 'global',
      });
      setShowAddText(false);
      setNewDocTitle('');
      setNewDocContent('');
      refetchDocs();
    } catch (err) {
      alert('Failed to add document: ' + (err.message || err));
    } finally {
      setAddingText(false);
    }
  }

  async function handleDeleteDoc(docId) {
    if (!confirm('Delete this document? This cannot be undone.')) return;
    try {
      await kbApi.deleteDocument(docId);
      refetchDocs();
    } catch (err) {
      alert('Delete failed: ' + (err.message || err));
    }
  }

  async function handleSaveLegacy() {
    setSaving(true);
    try {
      await kbApi.update(content);
      setSaved(true);
      refetchLegacy();
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      alert('Save failed: ' + err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Knowledge Base"
        description="Information the AI uses to answer customer questions"
        actions={
          <div style={{ display: 'flex', gap: '8px' }}>
            <Button variant="secondary" icon={Plus} onClick={() => setShowAddText(true)}>
              Add Text
            </Button>
            <Button icon={Upload} loading={uploading} onClick={() => fileInputRef.current?.click()}>
              Upload File
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.md,.pdf,.csv"
              style={{ display: 'none' }}
              onChange={handleFileUpload}
            />
          </div>
        }
      />

      {/* Tabs */}
      <div className="kb-tabs">
        <button className={`tab ${tab === 'documents' ? 'tab--active' : ''}`} onClick={() => setTab('documents')}>
          <BookOpen size={15} /> Documents {documents.length > 0 && <span className="tab-count-subtle">{documents.length}</span>}
        </button>
        <button className={`tab ${tab === 'quick-edit' ? 'tab--active' : ''}`} onClick={() => setTab('quick-edit')}>
          <FileText size={15} /> Quick Edit
        </button>
      </div>

      {/* Documents Tab */}
      {tab === 'documents' && (
        docsLoading ? <Spinner /> : (
          <>
            {/* Add text document modal */}
            {showAddText && (
              <div className="kb-add-text-card">
                <div className="kb-add-text-header">
                  <h4>Add Text Document</h4>
                  <button onClick={() => setShowAddText(false)}><X size={16} /></button>
                </div>
                <input
                  className="kb-add-title"
                  placeholder="Document title (e.g., Product FAQ, Pricing Info)"
                  value={newDocTitle}
                  onChange={e => setNewDocTitle(e.target.value)}
                />
                <textarea
                  className="kb-add-textarea"
                  placeholder="Paste your content here — product info, FAQs, pricing tables, service descriptions..."
                  value={newDocContent}
                  onChange={e => setNewDocContent(e.target.value)}
                  rows={10}
                />
                <div className="kb-add-actions">
                  <span className="kb-add-meta">{newDocContent.length} characters</span>
                  <Button size="sm" loading={addingText} onClick={handleAddText} disabled={!newDocTitle.trim() || !newDocContent.trim()}>
                    Add Document
                  </Button>
                </div>
              </div>
            )}

            {documents.length === 0 ? (
              <EmptyState
                icon={BookOpen}
                title="No documents yet"
                description="Upload files (.txt, .md, .pdf, .csv) or add text manually to build your knowledge base."
                action={
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <Button variant="secondary" icon={Plus} onClick={() => setShowAddText(true)}>Add Text</Button>
                    <Button icon={Upload} onClick={() => fileInputRef.current?.click()}>Upload File</Button>
                  </div>
                }
              />
            ) : (
              <div className="kb-doc-grid">
                {documents.map(doc => (
                  <div key={doc.id} className="kb-doc-card">
                    <div className="kb-doc-header">
                      <span className="kb-doc-icon">{DOC_TYPE_ICONS[doc.type] || '📄'}</span>
                      <div className="kb-doc-meta">
                        <span className="kb-doc-title">{doc.title}</span>
                        <span className="kb-doc-sub">
                          {doc.chunk_count} chunks · {(doc.char_count || 0).toLocaleString()} chars
                        </span>
                      </div>
                      <button className="kb-doc-delete" onClick={() => handleDeleteDoc(doc.id)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <div className="kb-doc-badges">
                      <Badge variant="default" size="sm">{doc.type}</Badge>
                      <Badge variant="gray" size="sm">{doc.scope}</Badge>
                      {doc.created_at && (
                        <span className="kb-doc-date">
                          {new Date(doc.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )
      )}

      {/* Quick Edit Tab */}
      {tab === 'quick-edit' && (
        legacyLoading ? <Spinner /> : (
          <div className="kb-editor">
            <div className="kb-meta">
              <span>{content.length} characters</span>
              <Button size="sm" icon={Save} loading={saving} onClick={handleSaveLegacy}>
                {saved ? 'Saved!' : 'Save'}
              </Button>
            </div>
            <textarea
              className="kb-textarea"
              value={content}
              onChange={e => { setContent(e.target.value); setSaved(false); }}
              placeholder="Enter your business information, FAQs, pricing, services..."
              rows={25}
            />
          </div>
        )
      )}
    </div>
  );
}
