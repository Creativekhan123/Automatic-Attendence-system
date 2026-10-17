import React from 'react';
import { Bus, RefreshCw, Settings, Monitor, Smartphone } from 'lucide-react';

export default function TopHeader({
  onRefresh,
  onOpenSettings,
  isRefreshing,
  cloudStatus,
  isDesktopMode,
  onToggleDesktopMode,
}) {
  const triggerHaptic = () => {
    if (navigator.vibrate) navigator.vibrate(25);
  };

  return (
    <header className="top-header">
      <div className="brand-section">
        <div className="brand-icon-box">
          <Bus size={22} strokeWidth={2.4} />
        </div>
        <div>
          <h1 className="brand-title">FleetPass</h1>
          <div className="brand-subtitle">
            <span className="live-beacon"></span>
            <span>{cloudStatus || 'Live Fleet Cloud'}</span>
          </div>
        </div>
      </div>

      <div className="header-actions">
        {/* PC / Mobile Layout Switcher */}
        <button
          className="icon-button"
          onClick={() => {
            triggerHaptic();
            onToggleDesktopMode();
          }}
          title={isDesktopMode ? 'Switch to Mobile Phone View' : 'Switch to PC Wide Dashboard'}
          style={{
            width: 'auto',
            padding: '6px 12px',
            fontSize: '0.78rem',
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: isDesktopMode
              ? 'rgba(99,102,241,0.2)'
              : 'rgba(255,255,255,0.06)',
            borderColor: isDesktopMode ? 'var(--accent-primary)' : 'var(--border-subtle)',
            color: isDesktopMode ? '#fff' : 'var(--text-secondary)',
          }}
        >
          {isDesktopMode ? <Monitor size={15} /> : <Smartphone size={15} />}
          <span>{isDesktopMode ? 'PC Mode' : 'Mobile'}</span>
        </button>

        <button
          className="icon-button"
          onClick={() => {
            triggerHaptic();
            onRefresh();
          }}
          title="Refresh Data"
        >
          <RefreshCw size={17} className={isRefreshing ? 'animate-spin' : ''} />
        </button>

        <button
          className="icon-button"
          onClick={() => {
            triggerHaptic();
            onOpenSettings();
          }}
          title="Cloud Settings"
        >
          <Settings size={18} />
        </button>
      </div>
    </header>
  );
}
