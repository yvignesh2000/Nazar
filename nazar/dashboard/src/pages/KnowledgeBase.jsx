import { useState, useEffect, useRef, useCallback } from 'react';
import { BookOpen, Save, FolderUp, Trash2, FileText, Plus, X, CheckCircle, AlertCircle, Upload, FolderPlus } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { kb as kbApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import './KnowledgeBase.css';

const DOC_TYPE_ICONS = {
  text: '📄', markdown: '📝', pdf: '📕', csv: '📊', html: '🌐',
};

const ALLOWED_EXTENSIONS = ['txt', 'md', 'pdf', 'csv', 'html', 'htm'];
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024;
const BATCH_SIZE = 20;

/**
 * Recursively read all file entries from a dropped directory via the
 * File System Access / DataTransferItem.webkitGetAsEntry() API.
 */
function readAllEntries(directoryEntry) {
  return new Promise((resolve) => {
    const files = [];
    const reader = directoryEntry.createReader();
    const readBatch = () => {
      reader.readEntries(async (entries) => {
        if (entries.length === 0) {
          resolve(files);
          return;
        }
        for (const entry of entries) {
          if (entry.isFile) {
            const file = await new Promise((res) => entry.file(res));
            // Attach a relative path so filtering/grouping works
            Object.defineProperty(file, 'webkitRelativePath', {
              value: entry.fullPath.replace(/^\//, ''),
              writable: false,
            });
            files.push(file);
          } else if (entry.isDirectory) {
            const nested = await readAllEntries(entry);
            files.push(...nested);
          }
        }
        // readEntries may batch results — keep reading until empty
        readBatch();
      });
    };
    readBatch();
  });
}

/**
 * Filter raw file list into { valid, invalid, oversized } buckets.
 */
function filterFiles(fileList) {
  const invalid = [];
  const oversized = [];
  const valid = [];

  for (const file of fileList) {
    const relativePath = file.webkitRelativePath || file.name;
    const fileName = file.name || '';
    const pathParts = relativePath.split('/');
    const hasHiddenSegment = pathParts.some(part => part.startsWith('.') && part.length > 1);

    if (hasHiddenSegment || fileName === 'Thumbs.db' || fileName === 'desktop.ini' || file.size === 0) {
      continue;
    }

    const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      invalid.push(relativePath);
    } else if (file.size > MAX_FILE_SIZE_BYTES) {
      oversized.push(relativePath);
    } else {
      valid.push(file);
    }
  }

  return { valid, invalid, oversized };
}

export default function KnowledgeBase() {
  const [tab, setTab] = useState('documents');

  const { data: docsData, loading: docsLoading, refetch: refetchDocs } = useApi(
    () => kbApi.listDocuments(),
    []
  );
  const [uploading, setUploading] = useState(false);
  const [uploadResults, setUploadResults] = useState(null);
  const [showAddText, setShowAddText] = useState(false);
  const [newDocTitle, setNewDocTitle] = useState('');
  const [newDocContent, setNewDocContent] = useState('');
  const [addingText, setAddingText] = useState(false);
  const folderInputRef = useRef(null);
  const fileInputRef = useRef(null);

  // ── Multi-folder queue ───────────────────────────────────────
  const [folderQueue, setFolderQueue] = useState([]);  // [{ name, files: File[] }]
  const [showUploadPanel, setShowUploadPanel] = useState(false);
  const [dragOver, setDragOver] = useState(false);

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

  // ── Drag & drop handlers ─────────────────────────────────────
  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);

    const items = Array.from(e.dataTransfer.items || []);
    const newFolders = [];

    for (const item of items) {
      const entry = item.webkitGetAsEntry?.() || item.getAsEntry?.();
      if (!entry) continue;

      if (entry.isDirectory) {
        const files = await readAllEntries(entry);
        if (files.length > 0) {
          newFolders.push({ name: entry.name, files });
        }
      } else if (entry.isFile) {
        // Single files dropped — group them as "Dropped Files"
        const file = await new Promise((res) => entry.file(res));
        Object.defineProperty(file, 'webkitRelativePath', {
          value: file.name,
          writable: false,
        });
        const existing = newFolders.find(f => f.name === 'Dropped Files');
        if (existing) {
          existing.files.push(file);
        } else {
          newFolders.push({ name: 'Dropped Files', files: [file] });
        }
      }
    }

    if (newFolders.length > 0) {
      setFolderQueue(prev => [...prev, ...newFolders]);
      setShowUploadPanel(true);
    }
  }, []);

  // ── Folder picker (input[webkitdirectory]) — queue-based ────
  function handleFolderPick(e) {
    const selectedFiles = Array.from(e.target.files || []);
    if (selectedFiles.length === 0) return;

    const rootFolderName = selectedFiles[0]?.webkitRelativePath?.split('/')[0] || 'Folder';

    // Deduplicate: don't add the same folder name again
    setFolderQueue(prev => {
      const alreadyQueued = prev.some(f => f.name === rootFolderName);
      if (alreadyQueued) return prev;
      return [...prev, { name: rootFolderName, files: selectedFiles }];
    });
    setShowUploadPanel(true);

    if (folderInputRef.current) folderInputRef.current.value = '';
  }

  // ── File picker for individual files ──────────────────────────
  function handleFilePick(e) {
    const selectedFiles = Array.from(e.target.files || []);
    if (selectedFiles.length === 0) return;

    // Add as a group called "Selected Files" or merge with existing
    setFolderQueue(prev => {
      const existing = prev.find(f => f.name === 'Selected Files');
      if (existing) {
        return prev.map(f =>
          f.name === 'Selected Files'
            ? { ...f, files: [...f.files, ...selectedFiles] }
            : f
        );
      }
      return [...prev, { name: 'Selected Files', files: selectedFiles }];
    });
    setShowUploadPanel(true);

    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  // ── Remove a folder from queue ───────────────────────────────
  function removeFolderFromQueue(index) {
    setFolderQueue(prev => prev.filter((_, i) => i !== index));
  }

  // ── Upload all queued folders ────────────────────────────────
  async function handleUploadAll() {
    if (folderQueue.length === 0) return;

    // Flatten all files from all queued folders
    const allFiles = folderQueue.flatMap(f => f.files);
    const { valid, invalid, oversized } = filterFiles(allFiles);

    const folderNames = folderQueue.map(f => f.name).join(', ');

    if (valid.length === 0) {
      const reasons = [];
      if (invalid.length > 0) reasons.push(`${invalid.length} unsupported file(s)`);
      if (oversized.length > 0) reasons.push(`${oversized.length} oversized file(s)`);
      alert(`No valid files found in: ${folderNames}.${reasons.length ? `\n${reasons.join(', ')}` : ''}`);
      return;
    }

    setUploading(true);
    setUploadResults(null);

    try {
      let uploaded = 0;
      let failed = 0;
      const errors = [];

      for (let index = 0; index < valid.length; index += BATCH_SIZE) {
        const batch = valid.slice(index, index + BATCH_SIZE);
        if (batch.length === 1) {
          try {
            await kbApi.uploadFile(batch[0], batch[0].name, 'global');
            uploaded += 1;
          } catch (err) {
            failed += 1;
            errors.push({ filename: batch[0].webkitRelativePath || batch[0].name, error: err.message || 'Upload failed' });
          }
        } else {
          const result = await kbApi.uploadFiles(batch, 'global');
          uploaded += result.uploaded || 0;
          failed += result.failed || 0;
          if (Array.isArray(result.errors) && result.errors.length > 0) {
            errors.push(...result.errors);
          }
        }
      }

      setUploadResults({
        uploaded,
        failed: failed + invalid.length + oversized.length,
        scanned: allFiles.length,
        folderNames,
        errors: [
          ...errors,
          ...invalid.map(filename => ({ filename, error: 'Unsupported file type' })),
          ...oversized.map(filename => ({ filename, error: 'File too large (max 5MB)' })),
        ],
      });

      // Clear queue on success
      setFolderQueue([]);
      setShowUploadPanel(false);
      refetchDocs();
      setTimeout(() => setUploadResults(null), 8000);
    } catch (err) {
      alert('Upload failed: ' + (err.message || err));
    } finally {
      setUploading(false);
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

  const totalQueuedFiles = folderQueue.reduce((sum, f) => sum + f.files.length, 0);

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
            <Button variant="secondary" icon={FolderUp} onClick={() => folderInputRef.current?.click()}>
              Add Folder
            </Button>
            <Button icon={Upload} onClick={() => setShowUploadPanel(p => !p)}>
              Upload Files
            </Button>
            {/* Hidden inputs */}
            <input
              ref={folderInputRef}
              type="file"
              {...{ webkitdirectory: '', directory: '' }}
              multiple
              style={{ display: 'none' }}
              onChange={handleFolderPick}
            />
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".txt,.md,.pdf,.csv,.html,.htm"
              style={{ display: 'none' }}
              onChange={handleFilePick}
            />
          </div>
        }
      />

      <div className="kb-tabs">
        <button className={`tab ${tab === 'documents' ? 'tab--active' : ''}`} onClick={() => setTab('documents')}>
          <BookOpen size={15} /> Documents
        </button>
        <button className={`tab ${tab === 'quick-edit' ? 'tab--active' : ''}`} onClick={() => setTab('quick-edit')}>
          <FileText size={15} /> Quick Edit
        </button>
      </div>

      {/* ── Upload Panel (drag-drop + queue) ─────────────────────── */}
      {showUploadPanel && (
        <div className="kb-upload-panel">
          <div className="kb-upload-panel-header">
            <h4>Upload to Knowledge Base</h4>
            <button className="kb-upload-panel-close" onClick={() => setShowUploadPanel(false)}><X size={16} /></button>
          </div>

          <div
            className={`kb-drop-zone ${dragOver ? 'kb-drop-zone--active' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <FolderUp size={32} strokeWidth={1.5} />
            <p className="kb-drop-zone-title">
              Drag & drop folders here
            </p>
            <p className="kb-drop-zone-sub">
              Drop multiple folders at once — or use the buttons below
            </p>
            <div className="kb-drop-zone-actions">
              <Button size="sm" variant="secondary" icon={FolderPlus} onClick={() => folderInputRef.current?.click()}>
                Pick Folder
              </Button>
              <Button size="sm" variant="secondary" icon={Plus} onClick={() => fileInputRef.current?.click()}>
                Pick Files
              </Button>
            </div>
          </div>

          {/* ── Queued folders list ───────────────────────────────── */}
          {folderQueue.length > 0 && (
            <div className="kb-queue">
              <div className="kb-queue-header">
                <span className="kb-queue-title">
                  {folderQueue.length} folder{folderQueue.length !== 1 ? 's' : ''} queued · {totalQueuedFiles} file{totalQueuedFiles !== 1 ? 's' : ''} total
                </span>
              </div>
              <ul className="kb-queue-list">
                {folderQueue.map((folder, i) => {
                  const { valid } = filterFiles(folder.files);
                  return (
                    <li key={`${folder.name}-${i}`} className="kb-queue-item">
                      <span className="kb-queue-icon">📁</span>
                      <span className="kb-queue-name">{folder.name}</span>
                      <span className="kb-queue-count">
                        {valid.length} valid / {folder.files.length} total
                      </span>
                      <button className="kb-queue-remove" title="Remove" onClick={() => removeFolderFromQueue(i)}>
                        <X size={14} />
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div className="kb-queue-actions">
                <Button size="sm" variant="secondary" onClick={() => setFolderQueue([])}>
                  Clear All
                </Button>
                <Button size="sm" icon={Upload} loading={uploading} onClick={handleUploadAll}>
                  {uploading ? 'Uploading…' : `Upload ${totalQueuedFiles} File${totalQueuedFiles !== 1 ? 's' : ''}`}
                </Button>
              </div>
            </div>
          )}

          {folderQueue.length === 0 && (
            <p className="kb-upload-hint">
              Tip: You can pick multiple folders one by one — they'll be queued and uploaded together. Or drag & drop multiple folders at once.
            </p>
          )}
        </div>
      )}

      {uploadResults && (
        <div className={`kb-upload-results ${uploadResults.failed > 0 ? 'kb-upload-results--partial' : 'kb-upload-results--success'}`}>
          <div className="kb-upload-results-summary">
            {uploadResults.uploaded > 0 && (
              <span className="kb-upload-success-msg">
                <CheckCircle size={14} /> {uploadResults.uploaded} file{uploadResults.uploaded !== 1 ? 's' : ''} uploaded
              </span>
            )}
            {uploadResults.failed > 0 && (
              <span className="kb-upload-error-msg">
                <AlertCircle size={14} /> {uploadResults.failed} file{uploadResults.failed !== 1 ? 's' : ''} skipped
              </span>
            )}
            {typeof uploadResults.scanned === 'number' && (
              <span className="kb-doc-sub">{uploadResults.scanned} file{uploadResults.scanned !== 1 ? 's' : ''} scanned</span>
            )}
            {uploadResults.folderNames && (
              <span className="kb-doc-sub">from: {uploadResults.folderNames}</span>
            )}
            <button className="kb-upload-results-close" onClick={() => setUploadResults(null)}><X size={14} /></button>
          </div>
          {uploadResults.errors?.length > 0 && (
            <ul className="kb-upload-error-list">
              {uploadResults.errors.map((err, i) => (
                <li key={i}><strong>{err.filename}</strong>: {err.error}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === 'documents' && (
        <>
          {documents.length > 0 && (
            <div className="kb-source-info">
              <BookOpen size={14} />
              <span>
                {documents.length} document{documents.length !== 1 ? 's' : ''} indexed.
                The AI uses <strong>all sources</strong> — uploaded files + Quick Edit content — when answering customer questions.
              </span>
            </div>
          )}

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

          {docsLoading ? <Spinner /> : (
            <>
              {documents.length === 0 && !showAddText ? (
                <EmptyState
                  icon={BookOpen}
                  title="No documents yet"
                  description="Upload folders or files to build your knowledge base. You can drag & drop multiple folders at once."
                  action={
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'center' }}>
                      <Button variant="secondary" icon={Plus} onClick={() => setShowAddText(true)}>Add Text</Button>
                      <Button variant="secondary" icon={FolderUp} onClick={() => folderInputRef.current?.click()}>Add Folder</Button>
                      <Button icon={Upload} onClick={() => setShowUploadPanel(true)}>Upload Files</Button>
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
                        <button className="kb-doc-delete" title="Delete" onClick={() => handleDeleteDoc(doc.id)}>
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
          )}
        </>
      )}

      {tab === 'quick-edit' && (
        legacyLoading ? <Spinner /> : (
          <div className="kb-editor">
            <div className="kb-sync-banner">
              <CheckCircle size={14} />
              <span>Quick Edit content is <strong>merged</strong> with uploaded documents when the AI answers customer questions. Both sources are used together.</span>
            </div>
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
