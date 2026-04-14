import { useNavigate } from 'react-router-dom';
import { GitBranch } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { pipeline as pipelineApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import './Pipeline.css';

const STAGE_COLORS = {
  new: '#6366f1', qualified: '#8b5cf6', proposal: '#f59e0b',
  negotiation: '#f97316', won: '#10b981', lost: '#ef4444',
};

export default function Pipeline() {
  const navigate = useNavigate();
  const { data, loading } = useApi(() => pipelineApi.get(), []);

  if (loading) return <Spinner />;

  const stages = data?.pipeline || [];

  return (
    <div className="page-content">
      <PageHeader title="Pipeline" description="Deal stages and contacts" />
      <div className="pipeline-board">
        {stages.map(stage => (
          <div key={stage.stage} className="pipeline-column">
            <div className="pipeline-column-header">
              <div className="pipeline-stage-dot" style={{ background: STAGE_COLORS[stage.stage] || '#6b7280' }} />
              <span className="pipeline-stage-name">{stage.stage}</span>
              <span className="pipeline-stage-count">{stage.contacts?.length || 0}</span>
            </div>
            <div className="pipeline-column-body">
              {(stage.contacts || []).map(c => (
                <div key={c.contact_id} className="pipeline-card" onClick={() => navigate(`/conversations/${c.contact_id}`)}>
                  <div className="pipeline-card-name">{c.name || 'Unknown'}</div>
                  {c.company && <div className="pipeline-card-company">{c.company}</div>}
                  <div className="pipeline-card-footer">
                    {c.deal_value > 0 && <Badge variant="success" size="sm">${c.deal_value.toLocaleString()}</Badge>}
                    {c.lead_score > 0 && <Badge variant="default" size="sm">Score: {c.lead_score}</Badge>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
