import React, { useState } from 'react';
import { X, Cloud, Check, Wifi, RotateCcw, ShieldCheck } from 'lucide-react';
import { getSupabaseConfig, saveSupabaseConfig, resetSupabaseConfig, getClient } from '../services/supabase';

export default function SettingsModal({ isOpen, onClose, onConfigUpdated }) {
  if (!isOpen) return null;

  const current = getSupabaseConfig();
  const [url, setUrl] = useState(current.url);
  const [key, setKey] = useState(current.key);
  const [testStatus, setTestStatus] = useState(null);
  const [isTesting, setIsTesting] = useState(false);

  const handleTest = async () => {
    setIsTesting(true);
    setTestStatus({ type: 'loading', message: 'Testing Supabase connection...' });
    const startTime = performance.now();
    try {
      const client = getClient();
      const { data, error } = await client.from('buses').select('bus_id').limit(1);
      const latency = Math.round(performance.now() - startTime);
      if (error) {
        setTestStatus({ type: 'error', message: `Failed: ${error.message}` });
      } else {
        setTestStatus({
          type: 'success',
          message: `Connected successfully (${latency}ms latency). Central cloud is online.`,
        });
      }
    } catch (err) {
      setTestStatus({ type: 'error', message: `Connection error: ${err.message}` });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSave = () => {
    saveSupabaseConfig(url, key);
    if (onConfigUpdated) onConfigUpdated();
    onClose();
  };

  const handleReset = () => {
    resetSupabaseConfig();
    const defaults = getSupabaseConfig();
    setUrl(defaults.url);
    setKey(defaults.key);
    if (onConfigUpdated) onConfigUpdated();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                background: 'rgba(99,102,241,0.15)',
                color: 'var(--accent-primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Cloud size={19} />
            </div>
            <div>
              <h3 className="modal-title">Cloud Configuration</h3>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                Supabase Central Fleet Database
              </p>
            </div>
          </div>
          <button className="icon-button" onClick={onClose} style={{ width: 32, height: 32 }}>
            <X size={18} />
          </button>
        </div>

        <div className="form-group">
          <label className="form-label">Supabase URL</label>
          <input
            type="text"
            className="form-input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-project.supabase.co"
          />
        </div>

        <div className="form-group">
          <label className="form-label">Publishable / Anon API Key</label>
          <input
            type="password"
            className="form-input"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Supabase API Key"
          />
        </div>

        {/* Test Result Banner */}
        {testStatus && (
          <div
            style={{
              padding: '10px 14px',
              borderRadius: 12,
              marginBottom: 16,
              fontSize: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              background:
                testStatus.type === 'success'
                  ? 'rgba(16,185,129,0.12)'
                  : testStatus.type === 'error'
                  ? 'rgba(244,63,94,0.12)'
                  : 'rgba(255,255,255,0.06)',
              color:
                testStatus.type === 'success'
                  ? 'var(--accent-emerald)'
                  : testStatus.type === 'error'
                  ? 'var(--accent-rose)'
                  : 'var(--text-secondary)',
              border: `1px solid ${
                testStatus.type === 'success'
                  ? 'rgba(16,185,129,0.3)'
                  : testStatus.type === 'error'
                  ? 'rgba(244,63,94,0.3)'
                  : 'var(--border-subtle)'
              }`,
            }}
          >
            <Wifi size={16} />
            <span>{testStatus.message}</span>
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleTest}
            disabled={isTesting}
            style={{ flex: 1 }}
          >
            {isTesting ? 'Pinging...' : 'Test Connection'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleReset}
            title="Reset to factory embedded credentials"
            style={{ width: 'auto', padding: '10px 14px' }}
          >
            <RotateCcw size={16} />
          </button>
        </div>

        <button className="btn-primary" onClick={handleSave}>
          <Check size={18} />
          <span>Save Cloud Settings</span>
        </button>
      </div>
    </div>
  );
}
