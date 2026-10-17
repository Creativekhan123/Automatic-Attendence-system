import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 20,
              background: 'rgba(244,63,94,0.15)',
              color: 'var(--accent-rose)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 14px',
            }}
          >
            <AlertTriangle size={28} />
          </div>
          <h3 style={{ fontSize: '1.15rem', color: '#fff', marginBottom: 6 }}>
            Something went wrong
          </h3>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: 18 }}>
            {this.state.error?.message || 'Unexpected application error.'}
          </p>
          <button
            className="btn-secondary"
            onClick={() => {
              this.setState({ hasError: false, error: null });
              window.location.reload();
            }}
            style={{ width: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <RefreshCw size={15} />
            <span>Reload Page</span>
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
