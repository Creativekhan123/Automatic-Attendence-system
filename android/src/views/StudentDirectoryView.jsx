import React, { useState, useMemo } from 'react';
import { Search, Edit3, Trash2, Bus, User, Shield, Check, X, AlertTriangle } from 'lucide-react';

export default function StudentDirectoryView({
  students,
  buses,
  onUpdateStudent,
  onDeleteStudent,
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedBusFilter, setSelectedBusFilter] = useState('ALL');

  // Edit Modal State
  const [editingStudent, setEditingStudent] = useState(null);
  const [editName, setEditName] = useState('');
  const [editClass, setEditClass] = useState('');
  const [editBus, setEditBus] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  // Delete Confirmation State
  const [studentToDelete, setStudentToDelete] = useState(null);

  const busOptions = useMemo(() => {
    return ['ALL', ...buses.map((b) => b.bus_id)];
  }, [buses]);

  const filteredStudents = useMemo(() => {
    return students.filter((s) => {
      const matchesBus = selectedBusFilter === 'ALL' || s.bus_id === selectedBusFilter;
      const q = searchTerm.toLowerCase();
      const matchesSearch =
        s.name.toLowerCase().includes(q) ||
        s.student_id.toLowerCase().includes(q) ||
        s.class_name.toLowerCase().includes(q) ||
        s.bus_id.toLowerCase().includes(q);
      return matchesBus && matchesSearch;
    });
  }, [students, selectedBusFilter, searchTerm]);

  const openEditModal = (student) => {
    setEditingStudent(student);
    setEditName(student.name);
    setEditClass(student.class_name);
    setEditBus(student.bus_id);
  };

  const handleSaveEdit = async () => {
    if (!editName.trim() || !editClass.trim()) return;
    setIsSaving(true);
    try {
      await onUpdateStudent(editingStudent.student_id, {
        name: editName.trim(),
        class_name: editClass.trim(),
        bus_id: editBus.trim(),
      });
      setEditingStudent(null);
    } catch (err) {
      alert('Error updating student: ' + err.message);
    } finally {
      setIsSaving(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!studentToDelete) return;
    try {
      await onDeleteStudent(studentToDelete.student_id);
      setStudentToDelete(null);
    } catch (err) {
      alert('Error deleting student: ' + err.message);
    }
  };

  return (
    <div>
      {/* Title */}
      <div style={{ marginBottom: 14 }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff' }}>Student Directory</h2>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          Manage rosters, edit bus routes, and handle student enrollment
        </p>
      </div>

      {/* Bus Filter Pills */}
      <div className="bus-selector-scroll">
        {busOptions.map((busId) => (
          <button
            key={busId}
            className={`bus-chip ${selectedBusFilter === busId ? 'active' : ''}`}
            onClick={() => setSelectedBusFilter(busId)}
          >
            <Bus size={14} />
            <span>{busId === 'ALL' ? 'All Buses' : busId}</span>
          </button>
        ))}
      </div>

      {/* Search Input */}
      <div className="search-container">
        <Search size={18} color="var(--text-muted)" />
        <input
          type="text"
          className="search-input"
          placeholder="Filter by name, ID, class or bus..."
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

      {/* Counter */}
      <div className="section-header">
        <h4>Registered Students</h4>
        <span className="section-counter">{filteredStudents.length} of {students.length}</span>
      </div>

      {/* Cards List */}
      <div className="student-list">
        {filteredStudents.length === 0 ? (
          <div className="empty-state">
            <User className="empty-state-icon" />
            <h4>No students found</h4>
            <p>Try searching for a different keyword or add a new student from the Enroll tab.</p>
          </div>
        ) : (
          filteredStudents.map((s) => (
            <div key={s.student_id} className="glass-card" style={{ padding: '14px 16px', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: 14,
                      background: 'linear-gradient(135deg, rgba(99,102,241,0.2), rgba(6,182,212,0.2))',
                      border: '1px solid var(--border-glow)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontFamily: 'var(--font-heading)',
                      fontWeight: 800,
                      color: 'var(--accent-primary)',
                      fontSize: '1.1rem',
                    }}
                  >
                    {s.name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <h4 style={{ fontSize: '0.96rem', fontWeight: 700, color: '#fff' }}>{s.name}</h4>
                    <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
                      <span className="badge-tag">ID: {s.student_id}</span>
                      <span className="badge-tag">Class {s.class_name}</span>
                      <span className="badge-tag" style={{ color: 'var(--accent-primary)' }}>{s.bus_id}</span>
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    className="icon-button"
                    onClick={() => openEditModal(s)}
                    title="Edit Student"
                    style={{ width: 34, height: 34 }}
                  >
                    <Edit3 size={15} />
                  </button>
                  <button
                    className="icon-button"
                    onClick={() => setStudentToDelete(s)}
                    title="Delete Student"
                    style={{ width: 34, height: 34, color: 'var(--accent-rose)', borderColor: 'rgba(244,63,94,0.3)' }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Edit Student Modal Sheet */}
      {editingStudent && (
        <div className="modal-overlay" onClick={() => setEditingStudent(null)}>
          <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Edit Student</h3>
              <button
                className="icon-button"
                onClick={() => setEditingStudent(null)}
                style={{ width: 32, height: 32 }}
              >
                <X size={18} />
              </button>
            </div>

            <div className="form-group">
              <label className="form-label">Student ID (Read-only)</label>
              <input
                type="text"
                className="form-input"
                value={editingStudent.student_id}
                disabled
                style={{ opacity: 0.6 }}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Full Name</label>
              <input
                type="text"
                className="form-input"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Student Name"
              />
            </div>

            <div className="form-group">
              <label className="form-label">Grade / Class</label>
              <input
                type="text"
                className="form-input"
                value={editClass}
                onChange={(e) => setEditClass(e.target.value)}
                placeholder="e.g. 5A"
              />
            </div>

            <div className="form-group">
              <label className="form-label">Assigned Fleet Bus</label>
              <select
                className="form-select"
                value={editBus}
                onChange={(e) => setEditBus(e.target.value)}
              >
                {buses.map((b) => (
                  <option key={b.bus_id} value={b.bus_id}>
                    {b.bus_id} ({b.bus_name || 'Fleet Bus'})
                  </option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
              <button
                className="btn-secondary"
                onClick={() => setEditingStudent(null)}
                style={{ flex: 1 }}
              >
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={handleSaveEdit}
                disabled={isSaving}
                style={{ flex: 2 }}
              >
                <Check size={18} />
                <span>{isSaving ? 'Saving...' : 'Update Details'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {studentToDelete && (
        <div className="modal-overlay" onClick={() => setStudentToDelete(null)}>
          <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
            <div style={{ textAlign: 'center', padding: '10px 0 20px' }}>
              <div
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 28,
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
              <h3 style={{ fontSize: '1.2rem', fontWeight: 800, color: '#fff', marginBottom: 6 }}>
                Delete Student Profile?
              </h3>
              <p style={{ fontSize: '0.86rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                Are you sure you want to remove <strong>{studentToDelete.name}</strong> (ID: {studentToDelete.student_id})?
                This student will be removed from bus attendance rosters.
              </p>
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button
                className="btn-secondary"
                onClick={() => setStudentToDelete(null)}
                style={{ flex: 1 }}
              >
                Cancel
              </button>
              <button
                className="btn-danger"
                onClick={handleConfirmDelete}
                style={{ flex: 1 }}
              >
                <Trash2 size={16} />
                <span>Delete Student</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
