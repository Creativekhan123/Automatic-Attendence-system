import React, { useState } from 'react';
import { Bus, Plus, Users, CheckCircle, ShieldCheck, PlusCircle, X, Check } from 'lucide-react';

export default function FleetOverviewView({ buses, students, attendanceRecords, selectedDate, onAddBus }) {
  const [showAddBusModal, setShowAddBusModal] = useState(false);
  const [newBusId, setNewBusId] = useState('');
  const [newBusName, setNewBusName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleCreateBus = async (e) => {
    e.preventDefault();
    if (!newBusId.trim()) return;
    setIsSubmitting(true);
    try {
      await onAddBus({
        bus_id: newBusId.trim(),
        bus_name: newBusName.trim() || `Bus ${newBusId.trim()}`,
        is_active: true,
      });
      setNewBusId('');
      setNewBusName('');
      setShowAddBusModal(false);
    } catch (err) {
      alert('Failed to add bus: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div>
      {/* Title */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff' }}>Fleet Buses</h2>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Active school transport vehicles & onboard cameras
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => setShowAddBusModal(true)}
          style={{ width: 'auto', padding: '8px 14px', fontSize: '0.82rem', borderRadius: 999 }}
        >
          <Plus size={16} />
          <span>Add Bus</span>
        </button>
      </div>

      {/* Bus Cards Grid */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {buses.map((bus) => {
          const assigned = students.filter((s) => s.bus_id === bus.bus_id);
          const presentToday = attendanceRecords.filter(
            (r) => r.bus_id === bus.bus_id && r.attendance_date === selectedDate
          ).length;
          const rate = assigned.length > 0 ? Math.round((presentToday / assigned.length) * 100) : 0;

          return (
            <div key={bus.bus_id} className="glass-card glass-card-interactive" style={{ padding: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div
                    style={{
                      width: 46,
                      height: 46,
                      borderRadius: 14,
                      background: 'linear-gradient(135deg, rgba(99,102,241,0.25), rgba(6,182,212,0.25))',
                      border: '1px solid var(--border-glow)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--accent-primary)',
                    }}
                  >
                    <Bus size={22} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1.05rem', fontWeight: 800, color: '#fff' }}>
                      {bus.bus_id}
                    </h3>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                      {bus.bus_name || 'School Bus Route'}
                    </p>
                  </div>
                </div>

                <div
                  style={{
                    padding: '4px 10px',
                    borderRadius: 999,
                    background: bus.is_active ? 'rgba(16,185,129,0.12)' : 'rgba(244,63,94,0.12)',
                    color: bus.is_active ? 'var(--accent-emerald)' : 'var(--accent-rose)',
                    border: `1px solid ${bus.is_active ? 'rgba(16,185,129,0.25)' : 'rgba(244,63,94,0.25)'}`,
                    fontSize: '0.72rem',
                    fontWeight: 700,
                  }}
                >
                  {bus.is_active ? 'ACTIVE' : 'INACTIVE'}
                </div>
              </div>

              {/* Progress & Stats */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
                <div className="metric-pill">
                  <span className="label">Assigned</span>
                  <span className="value" style={{ fontSize: '1.15rem' }}>{assigned.length}</span>
                </div>
                <div className="metric-pill emerald">
                  <span className="label">Boarded</span>
                  <span className="value" style={{ fontSize: '1.15rem' }}>{presentToday}</span>
                </div>
                <div className="metric-pill">
                  <span className="label">Rate</span>
                  <span className="value" style={{ fontSize: '1.15rem' }}>{rate}%</span>
                </div>
              </div>

              {/* Mini Progress Bar */}
              <div
                style={{
                  width: '100%',
                  height: 6,
                  borderRadius: 999,
                  background: 'rgba(255,255,255,0.08)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: `${rate}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, var(--accent-primary), var(--accent-emerald))',
                    borderRadius: 999,
                    transition: 'width 0.5s ease',
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Add Bus Modal */}
      {showAddBusModal && (
        <div className="modal-overlay" onClick={() => setShowAddBusModal(false)}>
          <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Register Fleet Bus</h3>
              <button
                className="icon-button"
                onClick={() => setShowAddBusModal(false)}
                style={{ width: 32, height: 32 }}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateBus}>
              <div className="form-group">
                <label className="form-label">Bus Identifier *</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. Bus03 or BUS-NORTH-01"
                  value={newBusId}
                  onChange={(e) => setNewBusId(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">Route / Bus Name</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. North Campus Express"
                  value={newBusName}
                  onChange={(e) => setNewBusName(e.target.value)}
                />
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setShowAddBusModal(false)}
                  style={{ flex: 1 }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={isSubmitting}
                  style={{ flex: 2 }}
                >
                  <Check size={18} />
                  <span>{isSubmitting ? 'Registering...' : 'Add Fleet Bus'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
