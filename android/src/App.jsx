import React, { useState, useEffect, useCallback } from 'react';
import TopHeader from './components/TopHeader';
import BottomNav from './components/BottomNav';
import LiveAttendanceView from './views/LiveAttendanceView';
import StudentDirectoryView from './views/StudentDirectoryView';
import FleetOverviewView from './views/FleetOverviewView';
import ReportsView from './views/ReportsView';
import SettingsModal from './views/SettingsModal';
import ErrorBoundary from './components/ErrorBoundary';
import { getClient } from './services/supabase';
import { Phone, X, Calendar, Bus, Clock, CheckCircle } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('live');
  const [students, setStudents] = useState([]);
  const [buses, setBuses] = useState([]);
  const [attendanceRecords, setAttendanceRecords] = useState([]);
  const [selectedBus, setSelectedBus] = useState('ALL');

  // Format today's date YYYY-MM-DD
  const getTodayDateString = () => {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const [selectedDate, setSelectedDate] = useState(getTodayDateString());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [cloudStatus, setCloudStatus] = useState('Connecting...');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [studentModal, setStudentModal] = useState(null);
  const [isDesktopMode, setIsDesktopMode] = useState(
    typeof window !== 'undefined' ? window.innerWidth >= 900 : false
  );

  // Fetch all fleet data
  const loadFleetData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const client = getClient();

      const [busesRes, studentsRes, attRes] = await Promise.all([
        client.from('buses').select('*').order('bus_id', { ascending: true }),
        client.from('students').select('*').eq('is_active', true).order('student_id', { ascending: true }),
        client.from('attendance').select('*').order('attendance_time', { ascending: false }),
      ]);

      if (busesRes.error) throw busesRes.error;
      if (studentsRes.error) throw studentsRes.error;
      if (attRes.error) throw attRes.error;

      setBuses(busesRes.data || []);
      setStudents(studentsRes.data || []);
      setAttendanceRecords(attRes.data || []);
      setCloudStatus('Fleet Cloud Live');
    } catch (err) {
      console.error('Fleet data fetch error:', err);
      setCloudStatus('Cloud Sync Issue');
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  // Initial load & real-time subscription
  useEffect(() => {
    loadFleetData();

    // Supabase Real-time updates for attendance
    try {
      const client = getClient();
      const channel = client
        .channel('realtime_attendance')
        .on(
          'postgres_changes',
          { event: '*', schema: 'public', table: 'attendance' },
          (payload) => {
            console.log('Realtime attendance update:', payload);
            loadFleetData();
          }
        )
        .subscribe();

      return () => {
        client.removeChannel(channel);
      };
    } catch (err) {
      console.warn('Realtime subscription not active:', err);
    }
  }, [loadFleetData]);

  // Operations
  const handleStudentCreated = async (newStudent, photo = null) => {
    let bridgeSuccess = false;

    // 1. If photo is present, send to Python Biometric Bridge to extract 512-D ArcFace embedding
    if (photo) {
      const host = window.location.hostname || 'localhost';
      const endpoints = [
        '/api/bridge/register', // Same-origin proxy via Vite (works with HTTPS dev server & mobile LAN)
        'http://localhost:5050/api/register', // Direct localhost (Electron desktop app)
        `http://${host}:5050/api/register`, // Direct LAN host
      ];

      for (const endpoint of endpoints) {
        try {
          const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              student_id: newStudent.student_id,
              name: newStudent.name,
              class_name: newStudent.class_name,
              bus_id: newStudent.bus_id,
              photo,
            }),
          });

          const data = await res.json().catch(() => null);
          if (res.ok && data?.success) {
            bridgeSuccess = true;
            console.log(`[FleetPass] 512-D ArcFace Biometrics registered via ${endpoint}:`, data);
            break;
          } else if (data?.error && res.status === 400) {
            // Model validation failure (e.g. no face or multiple faces)
            throw new Error(`Face Recognition Engine: ${data.error}`);
          }
        } catch (fetchErr) {
          if (fetchErr.message && fetchErr.message.includes('Face Recognition Engine:')) {
            throw fetchErr;
          }
          console.warn(`Bridge endpoint ${endpoint} unreachable:`, fetchErr.message);
        }
      }
    }

    // 2. Fallback to direct Supabase profile upsert if bridge was offline
    if (!bridgeSuccess) {
      const client = getClient();
      const { error } = await client.from('students').upsert(newStudent);
      if (error) throw error;

      if (photo) {
        alert(
          'Warning: Student details saved, but facial biometric embedding could not be generated because Python Biometric Bridge (port 5050) is unreachable.\n\nMake sure "python tools/biometric_bridge.py" is running on your PC so the camera attendance device can recognize this face.'
        );
      }
    }

    await loadFleetData();
  };

  const handleUpdateStudent = async (studentId, fields) => {
    const client = getClient();
    const { error } = await client.from('students').update(fields).eq('student_id', studentId);
    if (error) throw error;
    await loadFleetData();
  };

  const handleDeleteStudent = async (studentId) => {
    const client = getClient();
    // Soft delete or hard delete
    const { error } = await client.from('students').delete().eq('student_id', studentId);
    if (error) throw error;
    await loadFleetData();
  };

  const handleAddBus = async (busData) => {
    const client = getClient();
    const { error } = await client.from('buses').insert(busData);
    if (error) throw error;
    await loadFleetData();
  };

  return (
    <div className={`app-container ${isDesktopMode ? 'desktop-mode' : ''}`}>
      {/* Top Header */}
      <TopHeader
        onRefresh={loadFleetData}
        onOpenSettings={() => setIsSettingsOpen(true)}
        isRefreshing={isRefreshing}
        cloudStatus={cloudStatus}
        isDesktopMode={isDesktopMode}
        onToggleDesktopMode={() => setIsDesktopMode((prev) => !prev)}
      />

      {/* Main Content Dynamic Views */}
      <main className="main-content">
        <ErrorBoundary>
          {activeTab === 'live' && (
            <LiveAttendanceView
              students={students}
              buses={buses}
              attendanceRecords={attendanceRecords}
              selectedBus={selectedBus}
              onSelectBus={setSelectedBus}
              selectedDate={selectedDate}
              onSelectDate={setSelectedDate}
              onStudentClick={(student, att) => setStudentModal({ student, att })}
            />
          )}

          {activeTab === 'students' && (
            <StudentDirectoryView
              students={students}
              buses={buses}
              onUpdateStudent={handleUpdateStudent}
              onDeleteStudent={handleDeleteStudent}
            />
          )}

          {activeTab === 'add' && (
            <AddStudentView
              buses={buses}
              students={students}
              onStudentCreated={handleStudentCreated}
              onSwitchTab={setActiveTab}
            />
          )}

          {activeTab === 'buses' && (
            <FleetOverviewView
              buses={buses}
              students={students}
              attendanceRecords={attendanceRecords}
              selectedDate={selectedDate}
              onAddBus={handleAddBus}
            />
          )}

          {activeTab === 'reports' && (
            <ReportsView
              students={students}
              buses={buses}
              attendanceRecords={attendanceRecords}
              selectedDate={selectedDate}
              selectedBus={selectedBus}
            />
          )}
        </ErrorBoundary>
      </main>

      {/* Floating Bottom Navigation */}
      <BottomNav activeTab={activeTab} onChangeTab={setActiveTab} />

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onConfigUpdated={loadFleetData}
      />

      {/* Student Audit Detail Modal Sheet */}
      {studentModal && (
        <div className="modal-overlay" onClick={() => setStudentModal(null)}>
          <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Student Profile</h3>
              <button
                className="icon-button"
                onClick={() => setStudentModal(null)}
                style={{ width: 32, height: 32 }}
              >
                <X size={18} />
              </button>
            </div>

            <div style={{ textAlign: 'center', marginBottom: 20 }}>
              <div
                style={{
                  width: 64,
                  height: 64,
                  borderRadius: 20,
                  background: 'linear-gradient(135deg, #6366f1, #06b6d4)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.6rem',
                  fontWeight: 800,
                  color: '#fff',
                  margin: '0 auto 12px',
                  boxShadow: '0 8px 24px rgba(99,102,241,0.4)',
                }}
              >
                {studentModal.student.name.charAt(0).toUpperCase()}
              </div>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff' }}>
                {studentModal.student.name}
              </h3>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Student ID: {studentModal.student.student_id} • Grade {studentModal.student.class_name}
              </p>
            </div>

            {/* Attendance Status Card */}
            <div
              className="glass-card"
              style={{
                padding: 16,
                marginBottom: 16,
                borderColor: studentModal.att ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  Today's Status ({selectedDate})
                </span>
                <span
                  style={{
                    padding: '4px 10px',
                    borderRadius: 999,
                    fontSize: '0.74rem',
                    fontWeight: 700,
                    background: studentModal.att ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                    color: studentModal.att ? 'var(--accent-emerald)' : 'var(--accent-amber)',
                  }}
                >
                  {studentModal.att ? 'BOARDED (PRESENT)' : 'NOT YET BOARDED'}
                </span>
              </div>

              {studentModal.att && (
                <div style={{ marginTop: 12, display: 'flex', gap: 14, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Clock size={14} color="var(--accent-emerald)" />
                    {studentModal.att.attendance_time}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Bus size={14} color="var(--accent-primary)" />
                    {studentModal.att.bus_id}
                  </span>
                </div>
              )}
            </div>

            {/* Parent Contact Quick Action */}
            <a
              href="tel:100"
              className="btn-secondary"
              style={{
                textDecoration: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                marginBottom: 10,
              }}
            >
              <Phone size={16} />
              <span>Call Registered Parent / Guardian</span>
            </a>

            <button className="btn-primary" onClick={() => setStudentModal(null)}>
              <span>Done</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
