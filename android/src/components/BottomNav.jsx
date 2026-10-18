import React from 'react';
import { Activity, Users, Bus, FileSpreadsheet } from 'lucide-react';

export default function BottomNav({ activeTab, onChangeTab }) {
  const tabs = [
    { id: 'live', label: 'Live', icon: Activity },
    { id: 'students', label: 'Students', icon: Users },
    { id: 'buses', label: 'Fleet', icon: Bus },
    { id: 'reports', label: 'Reports', icon: FileSpreadsheet },
  ];

  const handleTabClick = (tabId) => {
    if (navigator.vibrate) navigator.vibrate(20);
    onChangeTab(tabId);
  };

  return (
    <nav className="bottom-dock">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            className={`nav-tab-item ${isActive ? 'active' : ''}`}
            onClick={() => handleTabClick(tab.id)}
          >
            <Icon size={20} strokeWidth={isActive ? 2.5 : 1.9} />
            <span className="nav-tab-label">{tab.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
