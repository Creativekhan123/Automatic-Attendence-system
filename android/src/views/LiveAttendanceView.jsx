import React, { useState, useMemo } from 'react';
import { Bus, CheckCircle2, Clock, Search, AlertCircle, Phone, Calendar, ArrowRight } from 'lucide-react';

export default function LiveAttendanceView({
  students,
  buses,
  attendanceRecords,
  selectedBus,
  onSelectBus,
  selectedDate,
  onSelectDate,
  onStudentClick,
}) {
  const [searchTerm, setSearchTerm] = useState('');

  // Generate unique bus list
  const busList = useMemo(() => {
    const list = buses.map((b) => b.bus_id);
    return ['ALL', ...list];
  }, [buses]);

  // Map attendance records for selected date
  const attendanceMap = useMemo(() => {
    const map = new Map();
    attendanceRecords.forEach((r) => {
      if (r.attendance_date === selectedDate) {
        map.set(r.student_id, r);
      }
    });
    return map;
  }, [attendanceRecords, selectedDate]);

  // Filter students based on selected bus
  const relevantStudents = useMemo(() => {
    if (selectedBus === 'ALL') return students;
    return students.filter((s) => s.bus_id === selectedBus);
  }, [students, selectedBus]);

  // Compute metrics
  const totalAssigned = relevantStudents.length;
  let presentCount = 0;
  relevantStudents.forEach((s) => {
    if (attendanceMap.has(s.student_id)) {
      presentCount++;
    }
  });

  const pendingCount = Math.max(0, totalAssigned - presentCount);
  const attendanceRate = totalAssigned > 0 ? Math.round((presentCount / totalAssigned) * 100) : 0;

  // Filter list by search term
  const filteredList = useMemo(() => {
    return relevantStudents.filter((s) => {
      const q = searchTerm.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        s.student_id.toLowerCase().includes(q) ||
        s.class_name.toLowerCase().includes(q) ||
        s.bus_id.toLowerCase().includes(q)
      );
    });
  }, [relevantStudents, searchTerm]);

  // SVG Circular Ring calculation
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (attendanceRate / 100) * circumference;

  // Palette generator for student avatar
  const getAvatarGradient = (id) => {
    const gradients = [
      'linear-gradient(135deg, #6366f1, #3b82f6)',
      'linear-gradient(135deg, #ec4899, #8b5cf6)',
      'linear-gradient(135deg, #10b981, #06b6d4)',
      'linear-gradient(135deg, #f59e0b, #ef4444)',
      'linear-gradient(135deg, #8b5cf6, #d946ef)',
    ];
    const index = (id.charCodeAt(0) || 0) % gradients.length;
    return gradients[index];
  };

  return (
    <div>
      {/* Date & Bus Filter Strip */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
          <Calendar size={15} color="var(--accent-primary)" />
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => onSelectDate(e.target.value)}
            style={{
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '8px',
              color: '#fff',
              padding: '4px 8px',
              fontSize: '0.82rem',
              outline: 'none',
              fontFamily: 'inherit',
            }}
          />
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>
          {selectedBus === 'ALL' ? 'Fleet-wide View' : `Active Route: ${selectedBus}`}
        </div>
      </div>

      {/* Bus Selector Scroll Pills */}
      <div className="bus-selector-scroll">
        {busList.map((busId) => {
          const isActive = selectedBus === busId;
          return (
            <button
              key={busId}
              className={`bus-chip ${isActive ? 'active' : ''}`}
              onClick={() => onSelectBus(busId)}
            >
              <Bus size={14} />
              <span>{busId === 'ALL' ? 'All Fleet' : busId}</span>
            </button>
          );
        })}
      </div>

      {/* Stats Hero Card with Circular Ring */}
      <div className="stats-hero-card">
        <div className="hero-header">
          <div className="hero-title-group">
            <h3>{selectedBus === 'ALL' ? 'Fleet Attendance' : `${selectedBus} Live Status`}</h3>
            <span>Auto-confirmed by onboard camera AI</span>
          </div>
          <div className="hero-badge">
            <span className="live-beacon"></span>
            <span>{presentCount > 0 ? 'Active Boarding' : 'Standby'}</span>
          </div>
        </div>

        <div className="hero-body">
          <div className="progress-ring-container">
            <svg width="96" height="96">
              <circle
                className="progress-ring-circle-bg"
                strokeWidth="8"
                fill="transparent"
                r={radius}
                cx="48"
                cy="48"
              />
              <circle
                className="progress-ring-circle"
                stroke="var(--accent-emerald)"
                strokeWidth="8"
                strokeDasharray={`${circumference} ${circumference}`}
                style={{ strokeDashoffset }}
                fill="transparent"
                r={radius}
                cx="48"
                cy="48"
              />
            </svg>
            <div className="progress-ring-center">
              <span className="progress-ring-percent">{attendanceRate}%</span>
              <span className="progress-ring-label">Boarded</span>
            </div>
          </div>

          <div className="metrics-grid">
            <div className="metric-pill emerald">
              <span className="label">Present</span>
              <span className="value">{presentCount}</span>
            </div>
            <div className="metric-pill amber">
              <span className="label">Pending</span>
              <span className="value">{pendingCount}</span>
            </div>
            <div className="metric-pill" style={{ gridColumn: 'span 2' }}>
              <span className="label">Total Registered</span>
              <span className="value" style={{ fontSize: '1.1rem' }}>{totalAssigned} Students</span>
            </div>
          </div>
        </div>
      </div>

      {/* Search Input */}
      <div className="search-container">
        <Search size={18} color="var(--text-muted)" />
        <input
          type="text"
          className="search-input"
          placeholder="Search student by name, ID or class..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
        {searchTerm && (
          <button
            onClick={() => setSearchTerm('')}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem' }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Section Header */}
      <div className="section-header">
        <h4>
          <CheckCircle2 size={16} color="var(--accent-emerald)" />
          <span>Student Roster</span>
        </h4>
        <span className="section-counter">{filteredList.length}</span>
      </div>

      {/* Student Cards List */}
      <div className="student-list">
        {filteredList.length === 0 ? (
          <div className="empty-state">
            <AlertCircle className="empty-state-icon" />
            <h4>No students found</h4>
            <p>Try searching for a different name, or select "All Fleet" from the bus selector above.</p>
          </div>
        ) : (
          filteredList.map((student) => {
            const att = attendanceMap.get(student.student_id);
            const isPresent = Boolean(att);

            return (
              <div
                key={student.student_id}
                className={`student-card ${isPresent ? 'present' : 'pending'}`}
                onClick={() => onStudentClick && onStudentClick(student, att)}
                style={{ cursor: 'pointer' }}
              >
                <div className="student-info">
                  <div
                    className="student-avatar"
                    style={{ background: getAvatarGradient(student.student_id) }}
                  >
                    {student.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="student-details">
                    <h4>{student.name}</h4>
                    <div className="student-meta">
                      <span className="badge-tag">ID: {student.student_id}</span>
                      <span className="badge-tag">Class {student.class_name}</span>
                      <span className="badge-tag">{student.bus_id}</span>
                    </div>
                  </div>
                </div>

                <div className={`status-badge ${isPresent ? 'present' : 'pending'}`}>
                  <span>{isPresent ? 'PRESENT' : 'PENDING'}</span>
                  <span className="status-time">
                    {isPresent ? (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                        <Clock size={11} />
                        {att.attendance_time?.slice(0, 5) || 'Checked in'}
                      </span>
                    ) : (
                      'Not Boarded'
                    )}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
