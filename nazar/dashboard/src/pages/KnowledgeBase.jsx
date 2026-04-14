import { useState, useEffect } from 'react';
import { BookOpen, Save } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { kb as kbApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Spinner from '../components/ui/Spinner';
import './KnowledgeBase.css';

export default function KnowledgeBase() {
  const { data, loading, refetch } = useApi(() => kbApi.get(), []);
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data?.content !== undefined) setContent(data.content);
  }, [data]);

  async function handleSave() {
    setSaving(true);
    try {
      await kbApi.update(content);
      setSaved(true);
      refetch();
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      alert('Save failed: ' + err.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader
        title="Knowledge Base"
        description="Information the AI uses to answer customer questions"
        actions={
          <Button icon={Save} loading={saving} onClick={handleSave}>
            {saved ? 'Saved!' : 'Save'}
          </Button>
        }
      />

      <div className="kb-editor">
        <div className="kb-meta">
          <span>{content.length} characters</span>
        </div>
        <textarea
          className="kb-textarea"
          value={content}
          onChange={e => { setContent(e.target.value); setSaved(false); }}
          placeholder="Enter your business information, FAQs, pricing, services..."
          rows={25}
        />
      </div>
    </div>
  );
}
